import os
import glob
import logging


logger = logging.getLogger(__name__)

_RESULT = dict()

def load_all_translations(pattern_path):
    """加载i18n目录下所有的properties文件"""
    global _RESULT

    pattern = os.path.join(pattern_path, "*.properties")

    for filepath in glob.glob(pattern):
        if not os.path.isfile(filepath):
            continue
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = f.read()
                for row in data.split('\n'):
                    row = row.strip()
                    if not row or row.startswith('#'):
                        continue
                    if ' = ' in row:
                        key, value = row.split(' = ', 1)
                        key_language = os.path.basename(filepath).replace("messages_", "").replace(".properties", "")
                        if not "zh" in key_language:
                            key_language = key_language.split("_")[0]
                        _RESULT[f"{key}_{key_language.lower()}"] = value.strip()
        except Exception as e:
            logger.error(f"Error loading {filepath}: {e}")

def translate(language_code: str, id: str, pattern_path: str):
    """
    获取指定语言和键的翻译
    "zh-cn": ("Chinese (Simplified)", "中文简体"),
    "zh-tw": ("Chinese (Traditional)", "中文繁体"),
    """
    global _RESULT
    language_code = language_code.replace("-", "_")
    if language_code == "zh_tw":
        language_code = "zh_hk"

    full_id = id + "_" + language_code.lower()

    result = _RESULT.get(full_id)
    if result is not None:
        return result

    if not _RESULT:
        load_all_translations(pattern_path)

    result = _RESULT.get(full_id)
    if result is not None:
        return result

    return _RESULT.get(f"{id}_en")


if __name__ == "__main__":
    print("Test 1: First call (should auto-load)")
    result1 = translate('zh_tw', '21109315dbba4000a894', 'conf/i18n/llm_shield')
    print(f"  Result: {result1}")
    print(f"  Loaded entries: {len(_RESULT)}")
