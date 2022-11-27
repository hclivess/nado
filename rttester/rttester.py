import requests
import time

url_dict = [{"name": "status",
            "url": "http://127.0.0.1:9173/status"}]

for item in url_dict:

    rt_list = []

    for _ in range(0, 10000):
        start_time = time.time()
        result = requests.get(url=item["url"])
        rt = time.time() - start_time
        rt_list.append(rt)

    with open(f"{item['name']}.txt", "w") as outfile:
        for entry in rt_list:
            outfile.write(str(entry))
            outfile.write("\n")
