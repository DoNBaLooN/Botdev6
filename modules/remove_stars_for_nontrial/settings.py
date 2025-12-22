"""Settings for remove_stars_for_nontrial module."""

# Remove mode: by exact callback_data or prefix
REMOVE_BY_PREFIX = False

# Exact callback_data for the stars payment button
STARS_CALLBACK_DATA = "pay_stars"

# Prefix for callback_data if using prefix removal
STARS_CALLBACK_PREFIX = "pay_stars"

# ID тарифа "Пробный период" в базе данных
# Проверки теперь будут идти по id, а не по имени
TRIAL_TARIFF_ID = 18

# Callback кнопки "💰 Ввести свою сумму"
# Удаляем её всегда через хук pay_menu_buttons
CUSTOM_AMOUNT_CALLBACK_DATA = "enter_custom_amount_stars"

# Enable debug logging
DEBUG_LOG = True
