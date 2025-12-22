"""
Роутер модуля технической поддержки для основного бота
"""

import asyncio
import subprocess
import sys
from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext

from logger import logger
from filters.admin import IsAdminFilter

# Импортируем систему управления процессами
try:
    from .installer import ProcessManager
    PROCESS_MANAGER_AVAILABLE = True
except ImportError:
    logger.warning("Process Manager не доступен, используем стандартную систему")
    PROCESS_MANAGER_AVAILABLE = False

router = Router()

# Название процесса бота поддержки
SUPPORT_PROCESS_NAME = "support_bot"

@router.message(Command("support"), IsAdminFilter())
async def support_command(message: Message, state: FSMContext):
    """Команда управления ботом поддержки (только для админов)"""
    keyboard = [
        [
            InlineKeyboardButton(text="🟢 Запустить бот поддержки", callback_data="support_start"),
            InlineKeyboardButton(text="🔴 Остановить бот поддержки", callback_data="support_stop")
        ],
        [
            InlineKeyboardButton(text="📊 Статус бота поддержки", callback_data="support_status"),
            InlineKeyboardButton(text="🔄 Перезапустить бот поддержки", callback_data="support_restart")
        ],
        [
            InlineKeyboardButton(text="🏠 На главную", callback_data="profile")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    await message.answer(
        "🛠 <b>Управление ботом технической поддержки</b>\n\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

@router.callback_query(F.data == "support_start", IsAdminFilter())
async def start_support_bot(callback: CallbackQuery):
    """Запуск бота поддержки"""
    try:
        # Завершаем все существующие процессы Support перед запуском нового
        if PROCESS_MANAGER_AVAILABLE:
            killed_processes = ProcessManager.kill_existing_bot_processes()
            if killed_processes:
                logger.info(f"Завершено {len(killed_processes)} существующих процессов Support")
        
        # Проверяем, запущен ли уже процесс
        if PROCESS_MANAGER_AVAILABLE:
            active_processes = ProcessManager.get_active_processes()
            if SUPPORT_PROCESS_NAME in active_processes:
                process = active_processes[SUPPORT_PROCESS_NAME]
                if process.poll() is None:
                    await callback.answer("❌ Бот поддержки уже запущен!", show_alert=True)
                    return
        # Путь к модулю поддержки
        support_dir = Path(__file__).parent
        # Сначала пробуем основную версию, если не получается - простую
        support_main = support_dir / "main.py"
        if not support_main.exists():
            support_main = support_dir / "simple_main.py"
        
        # Используем Python из виртуального окружения основного бота
        main_bot_dir = support_dir.parent.parent
        possible_venv_paths = [
            main_bot_dir / "venv" / "Scripts" / "python.exe",  # Windows
            main_bot_dir / "venv" / "bin" / "python",         # Linux/Mac
            main_bot_dir / ".venv" / "Scripts" / "python.exe", # Windows альтернатива
            main_bot_dir / ".venv" / "bin" / "python",        # Linux/Mac альтернатива
        ]
        
        python_executable = sys.executable
        for venv_python in possible_venv_paths:
            if venv_python.exists():
                python_executable = str(venv_python)
                break
        
        # Запускаем бот поддержки в отдельном процессе
        support_bot_process = subprocess.Popen(
            [python_executable, str(support_main)],
            cwd=str(support_dir),
            stdout=None,  # Не перехватываем вывод - избегаем buffer overflow
            stderr=None,  # Не перехватываем ошибки - избегаем buffer overflow
            start_new_session=True  # Создаем независимую session group
        )
        
        # Регистрируем процесс в менеджере
        if PROCESS_MANAGER_AVAILABLE:
            ProcessManager.register_process(SUPPORT_PROCESS_NAME, support_bot_process)
        
        logger.info(f"Запущен бот поддержки с PID: {support_bot_process.pid}")
        
        await callback.message.edit_text(
            "✅ <b>Бот поддержки запущен!</b>\n\n"
            f"🆔 PID процесса: <code>{support_bot_process.pid}</code>\n"
            f"🔧 Process Manager: {'✅ Активен' if PROCESS_MANAGER_AVAILABLE else '❌ Недоступен'}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="support_back_to_main")]
            ])
        )
        
        await callback.answer("✅ Бот поддержки успешно запущен!")
        
    except Exception as e:
        logger.error(f"Ошибка при запуске бота поддержки: {e}")
        await callback.answer("❌ Ошибка при запуске бота поддержки!", show_alert=True)

@router.callback_query(F.data == "support_stop", IsAdminFilter())
async def stop_support_bot(callback: CallbackQuery):
    """Остановка бота поддержки"""
    # Ищем процесс в менеджере
    support_bot_process = None
    if PROCESS_MANAGER_AVAILABLE:
        active_processes = ProcessManager.get_active_processes()
        if SUPPORT_PROCESS_NAME in active_processes:
            support_bot_process = active_processes[SUPPORT_PROCESS_NAME]
    
    if not support_bot_process or support_bot_process.poll() is not None:
        await callback.answer("❌ Бот поддержки не запущен!", show_alert=True)
        return
    
    try:
        support_bot_process.terminate()
        
        # Ждем завершения процесса
        try:
            support_bot_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            support_bot_process.kill()
            support_bot_process.wait()
        
        # Удаляем из менеджера процессов
        if PROCESS_MANAGER_AVAILABLE:
            ProcessManager.unregister_process(SUPPORT_PROCESS_NAME)
        
        logger.info("Бот поддержки остановлен")
        
        await callback.message.edit_text(
            "🔴 <b>Бот поддержки остановлен!</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="support_back_to_main")]
            ])
        )
        await callback.answer("✅ Бот поддержки успешно остановлен!")
        
    except Exception as e:
        logger.error(f"Ошибка при остановке бота поддержки: {e}")
        await callback.answer("❌ Ошибка при остановке бота поддержки!", show_alert=True)

@router.callback_query(F.data == "support_restart", IsAdminFilter())
async def restart_support_bot(callback: CallbackQuery):
    """Перезапуск бота поддержки"""
    # Ищем процесс в менеджере
    support_bot_process = None
    if PROCESS_MANAGER_AVAILABLE:
        active_processes = ProcessManager.get_active_processes()
        if SUPPORT_PROCESS_NAME in active_processes:
            support_bot_process = active_processes[SUPPORT_PROCESS_NAME]
    
    # Сначала останавливаем
    if support_bot_process and support_bot_process.poll() is None:
        try:
            support_bot_process.terminate()
            support_bot_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            support_bot_process.kill()
            support_bot_process.wait()
        except Exception as e:
            logger.error(f"Ошибка при остановке бота поддержки: {e}")
        
        # Удаляем из менеджера процессов
        if PROCESS_MANAGER_AVAILABLE:
            ProcessManager.unregister_process(SUPPORT_PROCESS_NAME)
    
    # Затем запускаем
    try:
        support_dir = Path(__file__).parent
        # Сначала пробуем основную версию, если не получается - простую
        support_main = support_dir / "main.py"
        if not support_main.exists():
            support_main = support_dir / "simple_main.py"
        
        # Используем Python из виртуального окружения основного бота
        main_bot_dir = support_dir.parent.parent
        possible_venv_paths = [
            main_bot_dir / "venv" / "Scripts" / "python.exe",  # Windows
            main_bot_dir / "venv" / "bin" / "python",         # Linux/Mac
            main_bot_dir / ".venv" / "Scripts" / "python.exe", # Windows альтернатива
            main_bot_dir / ".venv" / "bin" / "python",        # Linux/Mac альтернатива
        ]
        
        python_executable = sys.executable
        for venv_python in possible_venv_paths:
            if venv_python.exists():
                python_executable = str(venv_python)
                break
        
        support_bot_process = subprocess.Popen(
            [python_executable, str(support_main)],
            cwd=str(support_dir),
            stdout=None,  # Не перехватываем вывод - избегаем buffer overflow
            stderr=None,  # Не перехватываем ошибки - избегаем buffer overflow
            start_new_session=True  # Создаем независимую session group
        )
        
        # Регистрируем процесс в менеджере
        if PROCESS_MANAGER_AVAILABLE:
            ProcessManager.register_process(SUPPORT_PROCESS_NAME, support_bot_process)
        
        logger.info(f"Перезапущен бот поддержки с PID: {support_bot_process.pid}")
        
        await callback.message.edit_text(
            "🔄 <b>Бот поддержки перезапущен!</b>\n\n"
            f"🆔 PID процесса: <code>{support_bot_process.pid}</code>\n"
            f"🔧 Process Manager: {'✅ Активен' if PROCESS_MANAGER_AVAILABLE else '❌ Недоступен'}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="support_back_to_main")]
            ])
        )
        
        await callback.answer("✅ Бот поддержки успешно перезапущен!")
        
    except Exception as e:
        logger.error(f"Ошибка при перезапуске бота поддержки: {e}")
        await callback.answer("❌ Ошибка при перезапуске бота поддержки!", show_alert=True)

@router.callback_query(F.data == "support_status", IsAdminFilter())
async def support_bot_status(callback: CallbackQuery):
    """Проверка статуса бота поддержки"""
    # Ищем процесс в менеджере
    support_bot_process = None
    if PROCESS_MANAGER_AVAILABLE:
        active_processes = ProcessManager.get_active_processes()
        if SUPPORT_PROCESS_NAME in active_processes:
            support_bot_process = active_processes[SUPPORT_PROCESS_NAME]
    
    if support_bot_process and support_bot_process.poll() is None:
        status_text = (
            "🟢 <b>Бот поддержки работает</b>\n\n"
            f"🆔 PID процесса: <code>{support_bot_process.pid}</code>\n"
            f"⏱ Статус: Активен\n"
            f"🔧 Process Manager: {'✅ Активен' if PROCESS_MANAGER_AVAILABLE else '❌ Недоступен'}"
        )
        status_icon = "🟢"
    else:
        status_text = (
            "🔴 <b>Бот поддержки остановлен</b>\n\n"
            "❌ Процесс не найден или завершен\n"
            f"🔧 Process Manager: {'✅ Активен' if PROCESS_MANAGER_AVAILABLE else '❌ Недоступен'}"
        )
        status_icon = "🔴"
    
    await callback.message.edit_text(
        status_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="support_back_to_main")]
        ])
    )
    await callback.answer(f"{status_icon} Статус обновлен")

@router.callback_query(F.data == "support_back_to_main", IsAdminFilter())
async def back_to_main_support(callback: CallbackQuery):
    """Возврат к главному меню поддержки"""
    keyboard = [
        [
            InlineKeyboardButton(text="🟢 Запустить бот поддержки", callback_data="support_start"),
            InlineKeyboardButton(text="🔴 Остановить бот поддержки", callback_data="support_stop")
        ],
        [
            InlineKeyboardButton(text="📊 Статус бота поддержки", callback_data="support_status"),
            InlineKeyboardButton(text="🔄 Перезапустить бот поддержки", callback_data="support_restart")
        ],
        [
            InlineKeyboardButton(text="🏠 На главную", callback_data="profile")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    await callback.message.edit_text(
        "🛠 <b>Управление ботом технической поддержки</b>\n\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

# Функция для автоматического запуска бота поддержки при старте основного бота
async def auto_start_support_bot():
    """Автоматический запуск бота поддержки"""
    try:
        support_dir = Path(__file__).parent
        # Сначала пробуем основную версию, если не получается - простую
        support_main = support_dir / "main.py"
        if not support_main.exists():
            support_main = support_dir / "simple_main.py"
        
        # Используем Python из виртуального окружения основного бота
        main_bot_dir = support_dir.parent.parent
        possible_venv_paths = [
            main_bot_dir / "venv" / "Scripts" / "python.exe",  # Windows
            main_bot_dir / "venv" / "bin" / "python",         # Linux/Mac
            main_bot_dir / ".venv" / "Scripts" / "python.exe", # Windows альтернатива
            main_bot_dir / ".venv" / "bin" / "python",        # Linux/Mac альтернатива
        ]
        
        python_executable = sys.executable
        for venv_python in possible_venv_paths:
            if venv_python.exists():
                python_executable = str(venv_python)
                break
        
        if support_main.exists():
            support_bot_process = subprocess.Popen(
                [python_executable, str(support_main)],
                cwd=str(support_dir),
                stdout=None,  # Не перехватываем вывод - избегаем buffer overflow
                stderr=None,  # Не перехватываем ошибки - избегаем buffer overflow
                start_new_session=True  # Создаем независимую session group
            )
            
            # Регистрируем процесс в менеджере
            if PROCESS_MANAGER_AVAILABLE:
                ProcessManager.register_process(SUPPORT_PROCESS_NAME, support_bot_process)
            
            logger.info(f"Автоматически запущен бот поддержки с PID: {support_bot_process.pid}")
        else:
            logger.warning("Файл main.py или simple_main.py бота поддержки не найден")
            
    except Exception as e:
        logger.error(f"Ошибка автоматического запуска бота поддержки: {e}")

# Функция для остановки бота поддержки при завершении основного бота
async def cleanup_support_bot():
    """Остановка бота поддержки при завершении основного бота"""
    if PROCESS_MANAGER_AVAILABLE:
        # Используем Process Manager для корректного завершения всех процессов
        ProcessManager.shutdown_all_processes()
    else:
        # Fallback к старому методу
        logger.warning("Process Manager недоступен, используем fallback метод")


# Хуки для автоматического запуска/остановки бота поддержки
async def on_startup():
    """Автозапуск бота поддержки при старте основного бота"""
    logger.info("[Support Module] 🚀 Запуск модуля поддержки...")
    await auto_start_support_bot()


async def on_shutdown():
    """Автоостановка бота поддержки при завершении основного бота"""
    logger.info("[Support Module] 🛑 Завершение модуля поддержки...")
    await cleanup_support_bot()


# Регистрируем хуки в роутере
router.startup.register(on_startup)
router.shutdown.register(on_shutdown)