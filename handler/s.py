import requests


url = "https://s3.ap-south-1.amazonaws.com/shop.unicorn/pdp/iphone_15/iphone_15.html"
response = requests.get(url=url)

print(response.text)
with open("html/demo3.html", "w") as f:
    f.write(response.text)
