FROM harbor-hkidc.kcprd.com/base/dc-python-3.12.4:20240819.amd

# 环境设置
ARG branchName
ARG appName
ARG secPwd
ARG gitUrl
ARG commitId
ARG originBranchName

ENV branchName=${branchName} \
    secPwd=${secPwd} \
    appName=${appName} \
    GIT_URL=${gitUrl} \
    ORIGIN_BRANCH=${originBranchName} \
    COMMIT_SHORT_SHA=${commitId} \
    LANG=en_US.UTF-8 \
    PYTHONWARNINGS="ignore:Unverified HTTPS request" \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先复制依赖文件并安装依赖 (利用Docker层缓存)
# requirements.txt 含 -e ./vendor/TradingAgents，须在本层前复制该目录，否则 pip 报 invalid editable requirement
COPY requirements.txt ./
COPY vendor/TradingAgents ./vendor/TradingAgents
RUN pip3 install --no-cache-dir -r requirements.txt \
    -i https://nexus.kcprd.com/repository/mix-devops/simple \
    --trusted-host nexus.kcprd.com \
    --timeout 600

# 复制应用代码
COPY ./ ./

# 设置权限和准备运行环境
RUN chown -R 888:888 /app /tmp && \
    chmod -R 755 /tmp && \
    chmod +x /app/run.sh

ENTRYPOINT ["/app/run.sh"]
