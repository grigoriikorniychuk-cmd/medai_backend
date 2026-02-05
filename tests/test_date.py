from mlab_amo_async.amocrm_client import AsyncAmoCRMClient
from mlab_amo_async import Lead
from motor.motor_asyncio import AsyncIOMotorClient
from app.settings.paths import MONGO_URI, DB_NAME

amocrm_client = AsyncAmoCRMClient(
                client_id="906c06fb-1844-4892-9dc6-6a4e30129fdf",
                client_secret="nAmImvjJgpmcVzbenLztMWaWaYDOkQ8Qfna82L8FcZKipvSwmvbmPA0H7UhnJOKh",
                subdomain="stomdv",
                redirect_url="https://mlab-electronics.ru",
                mongo_uri=MONGO_URI,
                db_name=DB_NAME,
            )

leads = list(Lead.objects.all())
leads_count = len(leads)
print(f"Общее количество сделок: {leads_count}")


