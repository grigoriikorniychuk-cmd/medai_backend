from amocrm.v2 import tokens, Lead, custom_field, fields, Contact
from amocrm.v2 import Lead as _Lead
from datetime import datetime


class Lead(_Lead):
    yclients_time = custom_field.TextCustomField("Время записи, Yclients")
    yclients_date = custom_field.TextCustomField("Дата записи, Yclients")
    telegram = custom_field.TextCustomField("Telegram")
    telegram_phone = custom_field.TextCustomField("TelegramPhone")
    service = custom_field.TextCustomField("Услуга")


if __name__ == "__main__":
    tokens.default_token_manager(
        client_id="b705a118-1c62-42f4-8d75-84a6621950fd",
        client_secret="HjNH4d811QAkxWjI5RWSLhXAXWBBTYeZeYZ1K1x1ePXVc4q7Qe0xBoMLUPcY9YAj",
        subdomain="idealnayastudio",
        redirect_url="https://mlab-electronics.ru",
        storage=tokens.FileTokensStorage("./tokens"),  # by default FileTokensStorage
    )
    # tokens.default_token_manager.init(code="def5020006a0fd8a2a4ce3fe38d14d1726c937c880e1cbeaa53a3a8a5eca5038b235e43218008d85954f027db3d4621d8d29194599f66a36783e77b59498db11bb789864dfdce05194ef9c19dcd3fff0def27963e596fe85c9093efb4cdb96a958b9335c6655a97295efc8224fa823949d1fa3143243cc1822f34a04f38192946fca8afec9380f303a0af6cc2755f611e5c37d7f16d5bd657d7dda75a3d7523e8609f7a856908b5124ebf4b540d0d6da024cf718e588c0542dd7020f1931148ce21e637533995a03f634c894a310aed9796a5c104bcad13f5f2ab2e4b9c66ffbfbca2c4a230fbba2347105cd92e8235614051c48867c6be1564bbca1cb0cce6807f83df260c9d96c45d4175a9c197a4faec06c707a459778b3f13ed824e40418b34c0c15619ad0c5fa86fcde2593a7b28f12dc9b1fd8c53566ee8ead942dd0ffa53c43a6e0ae4f0a3e8e795c956b724310d4aca0c1a790caec761a5c5ad554c9be9ea7494e6f426b5232d0f8a362a0f6d06487c91b0cb08d6858d7b8e0f6235983a1d79fe6ff509651d89f4b23aab306f3d8d958a559a7cb1d73fb093d2a5b8752d536042d6fad264bab954a312858df2911a5627d701aea7398c8014cd35339cbe5f694b4247376f77f232bc0c91573504a47b71097f3633365bacefbee5122cbe3376b0d41064c2ea3994b", skip_error=False) #только для инициализации

    # print(tokens.default_token_manager.get_access_token())



    # Получение всех сделок из AmoCRM с фильтрацией по дате
    leads = list(Lead.objects.all())
    leads_count = len(leads)
    print(f"Общее количество сделок: {leads_count}")

    # Фильтрация сделок по дате с более подробной отладкой
    filtered_leads = []
    for lead in leads:
        # Проверяем кастомные поля напрямую в _data
        custom_fields = lead._data.get('custom_fields_values', [])
        
        for field in custom_fields:
            # Расширенная отладка
            if field.get('field_id') == 3130449:
                value = field.get('values', [{}])[0].get('value')
                
                if value == "11.05.2025":
                    filtered_leads.append(lead)
                    break

    # Вывод отфильтрованных сделок
    print(f"\nНайдено сделок с датой 11.05.2025: {len(filtered_leads)}")
    for lead in filtered_leads:
        print(f"ID: {lead.id}, Название: {lead.name}")
        
        # Вывод всех кастомных полей для найденных сделок
        custom_fields = lead._data.get('custom_fields_values', [])
        for field in custom_fields:
            print(f"{field.get('field_name', 'Неизвестное поле')}: {field.get('values', [{}])[0].get('value', 'Пусто')}")
        print("-" * 30)




    # Запись новой сделки в AmoCRM
    current_time = datetime.now()
    Lead.objects.create(
        name=f"AI_Сделка_{current_time.strftime('%d.%m.%Y %H:%M:%S')}",
        price=10000,
        custom_fields_values=[
            {
                "field_id": 3130447,  # ID поля "Время записи, Yclients"
                "values": [{"value": current_time.strftime("%H:%M")}]
            },
            {
                "field_id": 3130449,  # ID поля "Дата записи, Yclients"
                "values": [{"value": current_time.strftime("%d.%m.%Y")}]
            },

            {
                "field_id": 3130641,  # ID поля "Telegram"
                "values": [{"value": "@user_name444"}]
            },

            {
                "field_id": 3130843,  # ID поля "TelegramPhone"
                "values": [{"value": "+79004444444"}]
            },
            {
                "field_id": 3130937,  # ID поля "TelegramPhone"
                "values": [{"value": "Лазерная эпиляция подмышек"}]
            }
        ]
)

