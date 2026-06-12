
from dc_api_security.auth import AuthzUtil

print(AuthzUtil().encode_token(
    app_name="AI-WEB3-TRADDING-AGENT",
    path="/api/chat/query",
    method="POST",
    name="DC-KIA-QINGNIAO-SERVER",
    ak="DC-KIA-QINGNIAO-SERVER",
    sk="xe3PCY"
))

