# -*- coding: utf-8 -*-
"""
LLM Generate Skill

This skill handles LLM-based content generation with structured output.
"""

import json
import logging
from typing import Any, Dict

from agent.skills.base import BaseSkill
from agent.utils import jinja_render, utc_now_iso
from mcp.mcp_http_client import mcp_client
from llm.base import create_llm
from web.config import config

logger = logging.getLogger(__name__)


class LLMGenerateSkill(BaseSkill):
    """
    Skill for generating structured content using LLM.
    
    This skill retrieves prompts from MCP and uses LLM to generate
    structured JSON output.
    """
    name = "llm_generate"
    description = "Generate structured content using LLM"
    
    def __init__(self, prompt_name: str = "currency_insight_prompt"):
        """
        Initialize the skill.
        
        Args:
            prompt_name: Name of the prompt to retrieve from MCP
        """
        self.prompt_name = prompt_name
    
    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute LLM generation.
        
        Args:
            state: Current workflow state containing tool_result and symbol
            
        Returns:
            Updated state with insight_data
        """
        symbol = state.get("symbol", "")
        tool_result = state.get("tool_result")
        
        # If there was an error in previous step, propagate it
        if state.get("error"):
            logger.warning(f"Skipping LLM generation due to previous error: {state['error']}")
            return state
        
        logger.info(f"Generating insight for symbol={symbol} using LLM")
        
        try:
            # Try to get prompt from MCP first
            prompt = None
            try:
                prompt = await mcp_client.get_prompt(
                    name=self.prompt_name,
                    data={
                        "symbol": symbol,
                        "current_time": utc_now_iso()
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to get prompt from MCP: {e}, using local prompt")
            
            if not prompt:
                # Fallback to local prompt file
                try:
                    prompt = jinja_render(
                        self.prompt_name,
                        data={
                            "symbol": symbol,
                            "current_time": utc_now_iso()
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to load local prompt: {e}, using default")
                    prompt = self._get_default_prompt(symbol)
            
            # Prepare the tool result for LLM
            tool_result_str = json.dumps(tool_result, ensure_ascii=False) if tool_result else "{}"
            
            # Create LLM client
            llm, model_name = create_llm()
            
            # Build messages
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Please analyze the following data for {symbol} and generate a structured insight report:\n\n{tool_result_str}"}
            ]
            
            # Call LLM with JSON response format
            extra_body = None if config.use_azure_openai else {
                "chat_template_kwargs": {"enable_thinking": False},
            }
            
            response = await llm.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=4000,
                temperature=0.3,
                timeout=config.llm_api_timeout or 60.0,
                extra_body=extra_body
            )
            
            # Parse response
            response_content = response.choices[0].message.content
            
            # Try to extract JSON from response
            insight_data = self._parse_json_response(response_content, symbol)
            
            logger.info(f"LLM generation completed for symbol={symbol}")
            return {**state, "insight_data": insight_data, "prompt": prompt}
            
        except Exception as e:
            error_msg = f"LLM generation failed: {str(e)}"
            logger.exception(error_msg)
            # Return partial data on error
            return {
                **state, 
                "insight_data": self._get_error_response(symbol, str(e)),
                "error": error_msg
            }
    
    def _get_default_prompt(self, symbol: str) -> str:
        """Get default prompt if MCP prompt is not available."""
        return f"""You are a cryptocurrency analyst. Analyze the provided data for {symbol} and generate a structured JSON report.

The output must be a valid JSON object with the following structure:
{{
    "symbol": "{symbol}",
    "updateTime": "<current ISO timestamp>",
    "keyPoints": [
        {{"key": "Market Performance", "val": "<brief summary>"}}
    ],
    "pricePerformance": [
        {{"key": "Price Performance", "val": "<price analysis>"}}
    ],
    "technicalIndicators": {{
        "key": "Technical Indicators",
        "val": [
            {{"key": "RSI", "val": "<RSI analysis>"}},
            {{"key": "MACD", "val": "<MACD analysis>"}}
        ]
    }},
    "marketSentiment": {{
        "key": "Market Sentiment Analysis",
        "val": [{{"key": "Market Sentiment", "val": "<sentiment analysis>"}}]
    }},
    "keyTweets": {{
        "key": "Key Tweets",
        "val": ["<relevant tweet 1>", "<relevant tweet 2>"]
    }},
    "opportunitySummary": {{
        "key": "Opportunity Analysis Summary",
        "val": [
            {{"key": "Short-term Opportunity", "val": "<short-term analysis>"}},
            {{"key": "Mid-term Opportunity", "val": "<mid-term analysis>"}},
            {{"key": "Long-term Opportunity", "val": "<long-term analysis>"}}
        ]
    }}
}}

Important:
- Output ONLY the JSON object, no additional text
- If data is missing for any field, provide a reasonable placeholder or "Data not available"
- All text should be in English
- Be concise but informative
"""
    
    def _parse_json_response(self, response: str, symbol: str) -> dict:
        """Parse JSON from LLM response."""
        try:
            # Try direct JSON parse
            return json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            import re
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass
            
            # Try to find JSON object in response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass
            
            # Return error response if parsing fails
            logger.warning(f"Failed to parse JSON from LLM response for {symbol}")
            return self._get_error_response(symbol, "Failed to parse LLM response")
    
    def _get_error_response(self, symbol: str, error: str) -> dict:
        """Generate error response structure."""
        return {
            "symbol": symbol,
            "updateTime": utc_now_iso(),
            "keyPoints": [{"key": "Error", "val": error}],
            "pricePerformance": [],
            "technicalIndicators": {"key": "Technical Indicators", "val": []},
            "marketSentiment": {"key": "Market Sentiment Analysis", "val": []},
            "keyTweets": {"key": "Key Tweets", "val": []},
            "opportunitySummary": {"key": "Opportunity Analysis Summary", "val": []}
        }
