#!/bin/bash

echo "serverEnv: $serverEnv, branchName: $branchName", envName: $envName, VAULT_ADDRESS: $VAULT_ADDRESS, AWS_REGION: $AWS_REGION

# dev、sit环境
if [[ "$serverEnv" == "offline" ]];then
  export APOLLO_HOSTS=http://apollo-risk.kucoin:8080

elif [[ "$serverEnv" == "offlineXversion" ]];then
  export APOLLO_HOSTS=http://apollo-risk.kucoin:8080

# uat环境
elif [[ "$serverEnv" == "uat" ]];then
  export APOLLO_HOSTS=http://apollo-risk-uat.kucoin:8080/
  export no_proxy=localhost,.kcprd.com,kucoin.net,10.0.0.0/8,127.0.0.1,.kucoin,gw-2ybn2we1speuv8t4o5-vpc.cn-hongkong.pai-eas.aliyuncs.com,litellm-ali-uat.dc.kcprd.com,api.valuescan.io,kcapi.dexscan.trade

# IDC环境
elif [[ "$serverEnv" == "online" ]];then
  export APOLLO_HOSTS=http://apollo2.kucoin:8080

# 预发环境
elif [[ "$serverEnv" == "pre" ]];then
  export xversion=$branchName
  export APOLLO_HOSTS=http://apollo2.kucoin:8080
  export https_proxy=http://sec-mwg-http9090-d29cc2af8b4c9871.elb.ap-northeast-1.amazonaws.com:9090
  export no_proxy=localhost,.kcprd.com,kucoin.net,10.0.0.0/8,127.0.0.1,.kucoin,gw-2ybn2we1speuv8t4o5-vpc.cn-hongkong.pai-eas.aliyuncs.com,litellm-ali-uat.dc.kcprd.com,api.valuescan.io,kcapi.dexscan.trade
  echo "xversion: $xversion"

# IDC环境
elif [[ "$serverEnv" == "online" ]];then
  export APOLLO_HOSTS=http://apollo2.kucoin:8080
  export https_proxy=http://sec-mwg-http9090-d29cc2af8b4c9871.elb.ap-northeast-1.amazonaws.com:9090
  export no_proxy=localhost,.kcprd.com,kucoin.net,10.0.0.0/8,127.0.0.1,.kucoin,gw-2ybn2we1speuv8t4o5-vpc.cn-hongkong.pai-eas.aliyuncs.com,litellm-ali-uat.dc.kcprd.com,api.valuescan.io,kcapi.dexscan.trade

# 生产环境
else
  export APOLLO_HOSTS=http://apollo2.kucoin:8080
  export https_proxy=http://sec-mwg-http9090-d29cc2af8b4c9871.elb.ap-northeast-1.amazonaws.com:9090
  export no_proxy=localhost,.kcprd.com,kucoin.net,10.0.0.0/8,127.0.0.1,.kucoin,gw-2ybn2we1speuv8t4o5-vpc.cn-hongkong.pai-eas.aliyuncs.com,litellm-ali-uat.dc.kcprd.com,api.valuescan.io,kcapi.dexscan.trade
fi

export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

export LOG_PATH=/var/log/kucoin/${appName}
mkdir -p "$LOG_PATH"
echo "init LOG_PATH: $LOG_PATH"

exec python -m uvicorn main:app --host "0.0.0.0" --port 10240 --workers 1
