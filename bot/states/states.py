from aiogram.fsm.state import State, StatesGroup

# Определение состояний FSM для регистрации клиники
class ClinicRegistration(StatesGroup):
    name = State()
    amocrm_subdomain = State()
    client_id = State()
    client_secret = State()
    redirect_url = State()
    auth_code = State()
    amocrm_pipeline_id = State()
    monthly_limit = State()
    confirmation = State()

# Определение состояний FSM для запроса сделок по дате
class LeadsByDate(StatesGroup):
    date = State()
    client_id = State()

# Определение состояний FSM для работы со звонками
class CallsManagement(StatesGroup):
    lead_selection = State()
    call_selection = State()
    action_selection = State()

# Определение состояний FSM для генерации отчетов
class ReportGeneration(StatesGroup):
    start_date = State()
    end_date = State()
    clinic_id = State()
    admin_ids = State()
    confirmation = State()

# Состояния FSM для авторизации пользователя
class AuthStates(StatesGroup):
    awaiting_client_id = State() 