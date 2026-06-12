import requests
import json
import time

# 读取JSON文件
def load_mapping_file():
    with open('./line_num_id_mapping.json', 'r', encoding='utf-8') as f:
        return json.load(f)

# 保存JSON文件
def save_mapping_file(data):
    with open('./line_num_id_mapping_with_result.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# 请求API获取数据
def get_chat_data(session_id):
    url = "https://www.kucoin.com/_api/kia/chat/qa/history"
    
    payload = json.dumps({
        "sessionId": session_id,
        "selectType": "current"
    })
    headers = {
        'Cookie': 'x-visited=true; X_GRAY_TEMP_UUID=53fc94c0-076d-40f5-8365-58f84ccbf3cb; smidV2=202506261737327fb95f1f2a80c482d467a11adb49f992000b08aab7fa4f920; _fbp=fb.1.1750930670708.536132945; X-TRACE=k41J62m142wvKyVWBOgDeNJuV+xEf41StP40DAUMqGQ=; _cfuvid=eH3Kk7x3geSDma_C3gZOVF55S8DdzH8qHW8c0KR8gCg-1753182077615-0.0.1.1-604800000; kc_theme=light; _tea_utm_cache_586864={%22utm_source%22:%22cloud_mining%22}; _uetvid=39bd3270527111f0939149a6b51b5691; _gcl_au=1.1.450088660.1758800628; rtg_usr=v1.0:17513820779:1751625728939:1761899915701; cslfp=eyJ1dWlkQ2xpZW50IjoiZjJmMDA2NjItNmM5Ni00ZDZmLWJlNDEtYjkyMjg5ZGViYWM5Iiwia2V5IjoiOWQwOWZkOTE0MWNmOTA2NjRiNWZjY2FjYjUwY2NmYWI0YjFmNmM1ZTczZGFiYzcxZjI4MzlhZWE5MmViOTYxYiJ9; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%22248403857%22%2C%22first_id%22%3A%22197ab9978f62e11-0b090f618dcd028-17525636-1405320-197ab9978f73879%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E7%9B%B4%E6%8E%A5%E6%B5%81%E9%87%8F%22%2C%22%24latest_search_keyword%22%3A%22%E6%9C%AA%E5%8F%96%E5%88%B0%E5%80%BC_%E7%9B%B4%E6%8E%A5%E6%89%93%E5%BC%80%22%2C%22%24latest_referrer%22%3A%22%22%2C%22%24latest_utm_source%22%3A%22cloud_mining%22%7D%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMTk3YWI5OTc4ZjYyZTExLTBiMDkwZjYxOGRjZDAyOC0xNzUyNTYzNi0xNDA1MzIwLTE5N2FiOTk3OGY3Mzg3OSIsIiRpZGVudGl0eV9sb2dpbl9pZCI6IjI0ODQwMzg1NyJ9%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%24identity_login_id%22%2C%22value%22%3A%22248403857%22%7D%2C%22%24device_id%22%3A%22198456b269d27c9-0e37e7d6fbdb328-17525636-1405320-198456b269e3cd5%22%7D; _gid=GA1.2.1148325134.1764252999; WEBGRAY=beta_web:seo-cms-web-ssr.customer-web-ssr.public-web.ucenter-web-private-ssr; g_state={"i_l":0,"i_ll":1764310765901,"i_b":"Lg7KcIG38GZXP/JjiGk7d1ExuOhgpFslofVSX1JbNTU"}; AWSALB=m5nqcK+nO/b87+vhLbJltr8CxusqKk08imkn86uNcpNjZ18VmZdSChKn9v2ltRG4Hh7z+a35Kwc1QimCD/yslgQwZ/87HOEagcdv9mIFdtCrzV9j4dUoUCNHzOkL; AWSALBCORS=m5nqcK+nO/b87+vhLbJltr8CxusqKk08imkn86uNcpNjZ18VmZdSChKn9v2ltRG4Hh7z+a35Kwc1QimCD/yslgQwZ/87HOEagcdv9mIFdtCrzV9j4dUoUCNHzOkL; SESSION=NzljYTUyMjQtZDNkNy00MTMwLThhN2YtZTgyZDJiNjdmODg0; JSESSIONID=DCFF7A406BB3DA90A1FA19E20278EDDF; __cf_bm=3hikVM66rRC7jSZP7Q3imDNOVYN__c1z3ZSik8DPKrM-1764312521-1.0.1.1-kPQVoHXBiIliD2U1S.mVGTxLvOww18BQFzNGaaBzzMgZao.PBwHzdTf.fSqoNa.8Y.synbL66NXfMBQLAg7HkOybdjr1h1katITDeMgZF4M; cf_clearance=58yBHSxzYb4zYkA6ZGn3mDPkw1iULkRIjjaDb.Kgm4Q-1764312522-1.2.1.1-Q1sfL7wek6OQeeiCgQyXEMTIwVuyh3BzbbjoAeh3Nubmw.OoKrb1Dr5X7Y67ceNU48H6XPi1wWGB_lAzZDvRTPSb7Bc6FMEzLtaNFZzKbi8.drzuIfLWwHBe5QPqi5U2rMJVSh.Kaujpgc43oKLxOrnsXVxBIWtCkBH4l06x6yYRXuqsPnitlYdpkdxR_VzGAAQl7T08xV.FBFXQ.b1MHudqEokory46Uv9FqcYoDSo; X-GRAY=xgray-market-operation-11-15&xgray-kcop1127&xgray-kcmg-20251127; X_GRAY_TMP=1764312347597; .thumbcache_c294bfec3668b22bff5f6aa9bb528f6a=xT4nWlM1hmGu5J+BYbU+Rhe2W2Kx7RNXLtD5gwe6zKeabHdYqhdITuAAMBGbZZSOWwu2ovZqgoQJR9vcKpFKkg%3D%3D; _ga=GA1.1.1364451098.1761109746; _ga_YHWW24NNH9=GS2.1.s1764310793$o9$g1$t1764312526$j60$l0$h0',
        'Content-Type': 'application/json'
    }
    
    try:
        response = requests.request("POST", url, headers=headers, data=payload)
        if response.status_code == 200:
            return response.json().get('data')
        else:
            print(f"请求失败，状态码: {response.status_code}")
            return None
    except Exception as e:
        print(f"请求出错: {e}")
        return None

def main():
    # 读取映射文件
    print("正在读取映射文件...")
    mapping_data = load_mapping_file()
    
    total_records = len(mapping_data)
    print(f"总共需要处理 {total_records} 条记录")
    
    # 遍历每个记录
    for i, (key, record) in enumerate(mapping_data.items(), 1):
        session_id = record.get('sessionId')
        if not session_id:
            print(f"记录 {key} 没有 sessionId，跳过")
            continue
            
        print(f"正在处理第 {i}/{total_records} 条记录 (key: {key})")
        
        # 请求API获取数据
        data = get_chat_data(session_id)
        
        if data is not None:
            # 将数据保存到记录中
            mapping_data[key]['data'] = data
            print(f"成功获取数据并保存到记录 {key}")
        else:
            print(f"获取记录 {key} 的数据失败")
        
        # 添加延迟避免请求过于频繁
        time.sleep(0.5)
        
        # 每处理10条记录保存一次文件
        if i % 10 == 0:
            print(f"已处理 {i} 条记录，保存文件...")
            save_mapping_file(mapping_data)
    
    # 最终保存文件
    print("所有记录处理完成，保存最终文件...")
    save_mapping_file(mapping_data)
    print("完成！")

if __name__ == "__main__":
    main()