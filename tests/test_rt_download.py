import requests
import os

# URL для теста
url = "https://api.cloudpbx.rt.ru/amo/widget/get_temp_record_url/?session_id=SD5b-ZlLJAE7NZNJl&account_id=30189490"

# --- 1. Попытка скачать напрямую ---
print("--- Тест 1: Прямое скачивание ---")
try:
        # Отключаем проверку SSL-сертификата, так как на сервере он самоподписанный
    response_direct = requests.get(url, timeout=20, verify=False)
    print(f"Статус-код (напрямую): {response_direct.status_code}")
    if response_direct.ok:
        with open("record_direct.mp3", "wb") as f:
            f.write(response_direct.content)
        print("Файл 'record_direct.mp3' успешно скачан.")
    else:
        print(f"Ошибка (напрямую): {response_direct.text}")
except requests.exceptions.RequestException as e:
    print(f"Исключение при прямом скачивании: {e}")

print("\n" + "="*40 + "\n")

# --- 2. Попытка скачать через SOCKS5 прокси ---
print("--- Тест 2: Скачивание через SOCKS5 прокси ---")

# Данные прокси: ip:port:user:password
PROXY_STRING = "45.196.121.101:63613:nraNmsdP:5TFRSPJz"

parts = PROXY_STRING.split(':')
if len(parts) == 4:
    ip, port, user, password = parts
    # Используем схему socks5h, она лучше подходит для работы с доменными именами
    proxy_url = f"socks5h://{user}:{password}@{ip}:{port}"
    
    proxies = {
        "http": proxy_url,
        "https": proxy_url
    }

    print(f"Используем прокси: {proxy_url.replace(password, '****')}")
    try:
        response_proxy = requests.get(url, proxies=proxies, timeout=30, verify=False)
        print(f"Статус-код: {response_proxy.status_code}")
        if response_proxy.ok:
            with open("record_proxy.mp3", "wb") as f:
                f.write(response_proxy.content)
            print("УСПЕХ! Файл 'record_proxy.mp3' скачан через прокси.")
        else:
            print(f"Ошибка: {response_proxy.text[:200]}")
    except requests.exceptions.RequestException as e:
        print(f"Исключение при скачивании через прокси: {e}")
else:
    print("Ошибка: неверный формат строки для прокси.")
