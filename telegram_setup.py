import requests
TOKEN = "8793787115:AAFR0t6vkAKQphhCz4xeniqgekCGqdJ9SVg"
r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates")
print(r.json())
