import time

import matplotlib.pyplot as plt
import requests

url_dict = [{"name": "status",
             "url": "http://89.25.168.195:9173/status"}]

while True:
    for item in url_dict:

        rt_list = []
        x_list = []

        for y in range(0, 1000):
            try:
                start_time = time.time()
                result = requests.get(url=item["url"])
                rt = time.time() - start_time
                rt_list.append(rt)
                x_list.append(y)
            except Exception as e:
                print(f"Exception: {e}")

        x_axis = x_list
        y_axis = rt_list

        plt.ion()

        plt.plot(x_axis, y_axis)
        plt.draw()
        plt.pause(0.01)
        plt.clf()
