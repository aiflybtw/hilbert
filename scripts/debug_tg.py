"""
debug_tg.py — запусти локально, покажет реальную структуру HTML со страницы.
Вывод скопируй сюда — поправим селекторы.

    python debug_tg.py
"""

import requests
from bs4 import BeautifulSoup

CHANNEL = "devops_jobs"

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
})

url = f"https://t.me/s/{CHANNEL}"
print(f"GET {url}")
resp = session.get(url, timeout=15)
print(f"Status: {resp.status_code}")
print(f"Content-Length: {len(resp.text)}\n")

soup = BeautifulSoup(resp.text, "lxml")

# -- считаем ключевые элементы ----------------------------------------
checks = [
    ("[data-post]",                 soup.select("[data-post]")),
    (".tgme_widget_message_wrap",   soup.select(".tgme_widget_message_wrap")),
    (".tgme_widget_message_bubble", soup.select(".tgme_widget_message_bubble")),
    ("time[datetime]",              soup.select("time[datetime]")),
    (".tgme_widget_message_text",   soup.select(".tgme_widget_message_text")),
    ("a.tme_messages_more",         soup.select("a.tme_messages_more")),
]

print("=== SELECTOR COUNTS ===")
for selector, results in checks:
    print(f"  {selector:<40} → {len(results)}")

# -- первые 3 элемента с data-post ------------------------------------
print("\n=== FIRST 3 [data-post] ===")
for el in soup.select("[data-post]")[:3]:
    print(f"  tag={el.name} class={el.get('class')} data-post={el.get('data-post')!r}")

# -- первые 3 time тега -----------------------------------------------
print("\n=== FIRST 3 time[datetime] ===")
for el in soup.select("time[datetime]")[:3]:
    print(f"  datetime={el['datetime']!r}  parent.class={el.parent.get('class')}")

# -- пагинация --------------------------------------------------------
print("\n=== PAGINATION ===")
more = soup.select_one("a.tme_messages_more")
print(f"  a.tme_messages_more : {more}")
# иногда класс называется иначе — поищем все <a> с data-before
for a in soup.select("a[data-before]"):
    print(f"  a[data-before] : class={a.get('class')} data-before={a.get('data-before')}")

# -- первые 500 символов тела (чтобы видеть реальный HTML) ------------
print("\n=== BODY SNIPPET (first 1000 chars) ===")
body = soup.find("body")
print((body.get_text("\n", strip=True) if body else resp.text)[:1000])
