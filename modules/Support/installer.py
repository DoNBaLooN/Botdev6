#!/usr/bin/env python3
"""
Автоматический установщик зависимостей для модуля Support
Обеспечивает автоматическую установку всех необходимых пакетов перед запуском модуля
"""

import os
import subprocess
import sys
import logging
import signal
import threading
import atexit
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from logging.handlers import RotatingFileHandler

logger = logging.getLogger(__name__)

# Глобальные переменные для управления процессами
_module_processes: Dict[str, subprocess.Popen] = {}
_shutdown_event = threading.Event()
_process_lock = threading.Lock()

class SupportInstaller:
    """Класс для автоматической установки зависимостей модуля Support"""
    
    def __init__(self):
        self.module_dir = Path(__file__).parent
        self.requirements_file = self.module_dir / "requirements.txt"
        self.main_bot_dir = self.module_dir.parent.parent
        self.python_executable = sys.executable
        
        # Пытаемся найти виртуальное окружение основного бота
        possible_venv_paths = [
            self.main_bot_dir / "venv" / "Scripts" / "python.exe",  # Windows
            self.main_bot_dir / "venv" / "bin" / "python",         # Linux/Mac
            self.main_bot_dir / ".venv" / "Scripts" / "python.exe", # Windows альтернатива
            self.main_bot_dir / ".venv" / "bin" / "python",        # Linux/Mac альтернатива
        ]
        
        for venv_python in possible_venv_paths:
            if venv_python.exists():
                self.python_executable = str(venv_python)
                logger.info(f"Найден Python виртуального окружения: {self.python_executable}")
                break
        else:
            logger.info(f"Используется системный Python: {self.python_executable}")
    
    def check_package_installed(self, package_name: str) -> bool:
        """Проверяет, установлен ли пакет"""
        try:
            result = subprocess.run(
                [self.python_executable, "-c", f"import {package_name.split('==')[0].split('>=')[0].replace('-', '_')}"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, Exception) as e:
            logger.debug(f"Ошибка при проверке пакета {package_name}: {e}")
            return False
    
    def parse_requirements(self) -> List[str]:
        """Парсит файл requirements.txt и возвращает список пакетов"""
        if not self.requirements_file.exists():
            logger.warning(f"Файл requirements.txt не найден: {self.requirements_file}")
            return []
        
        packages = []
        try:
            with open(self.requirements_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Пропускаем комментарии и пустые строки
                    if line and not line.startswith('#'):
                        packages.append(line)
            
            logger.info(f"Найдено {len(packages)} пакетов в requirements.txt")
            return packages
            
        except Exception as e:
            logger.error(f"Ошибка при чтении requirements.txt: {e}")
            return []
    
    def install_package(self, package: str) -> bool:
        """Устанавливает отдельный пакет"""
        try:
            logger.info(f"Установка пакета: {package}")
            
            result = subprocess.run(
                [self.python_executable, "-m", "pip", "install", package, "--quiet"],
                capture_output=True,
                text=True,
                timeout=300  # 5 минут на установку одного пакета
            )
            
            if result.returncode == 0:
                logger.info(f"✅ Пакет {package} успешно установлен")
                return True
            else:
                logger.error(f"❌ Ошибка установки {package}: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"❌ Таймаут при установке {package}")
            return False
        except Exception as e:
            logger.error(f"❌ Исключение при установке {package}: {e}")
            return False
    
    def install_missing_packages(self) -> Tuple[bool, List[str]]:
        """Проверяет и устанавливает отсутствующие пакеты"""
        packages = self.parse_requirements()
        if not packages:
            logger.info("Нет пакетов для установки")
            return True, []
        
        missing_packages = []
        failed_packages = []
        
        # Определяем отсутствующие пакеты
        for package in packages:
            package_name = package.split('==')[0].split('>=')[0].split('<=')[0]
            if not self.check_package_installed(package_name):
                missing_packages.append(package)
        
        if not missing_packages:
            logger.info("✅ Все необходимые пакеты уже установлены")
            return True, []
        
        logger.info(f"Найдено {len(missing_packages)} отсутствующих пакетов")
        
        # Устанавливаем отсутствующие пакеты
        for package in missing_packages:
            if not self.install_package(package):
                failed_packages.append(package)
        
        success = len(failed_packages) == 0
        if success:
            logger.info("✅ Все зависимости успешно установлены")
        else:
            logger.error(f"❌ Не удалось установить: {failed_packages}")
        
        return success, failed_packages
    
    def create_env_file_if_missing(self) -> bool:
        """Создает .env файл из .env.example если он отсутствует"""
        env_file = self.module_dir / ".env"
        env_example = self.module_dir / ".env.example"
        
        if env_file.exists():
            return True
        
        if not env_example.exists():
            logger.warning("Файл .env.example не найден, создаем базовый .env")
            try:
                with open(env_file, 'w', encoding='utf-8') as f:
                    f.write("""# Support Bot Configuration
# Скопируйте и заполните необходимые значения

# Токен бота поддержки
BOT_TOKEN=your_support_bot_token_here

# ID чата поддержки (группа/канал где будут создаваться топики)
SUPPORT_CHAT_ID=0

# ID администраторов (через запятую)
ADMIN_IDS=123456789,987654321

# Название проекта
PROJECT_NAME=VPN BOT

# Username основного бота (без @)
MAIN_BOT_USERNAME=your_main_bot_username

# Отладка
DEBUG=False
LOG_LEVEL=INFO
""")
                logger.info("✅ Создан базовый .env файл")
                return True
            except Exception as e:
                logger.error(f"❌ Ошибка создания .env файла: {e}")
                return False
        
        try:
            # Копируем из .env.example
            import shutil
            shutil.copy2(env_example, env_file)
            logger.info("✅ Создан .env файл из .env.example")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка копирования .env.example: {e}")
            return False
    
    def validate_installation(self) -> bool:
        """Валидирует установку модуля"""
        try:
            # Проверяем основные файлы
            required_files = [
                "main.py", "config.py", "support_handler.py", 
                "router.py", "requirements.txt"
            ]
            
            missing_files = []
            for file in required_files:
                if not (self.module_dir / file).exists():
                    missing_files.append(file)
            
            if missing_files:
                logger.error(f"❌ Отсутствуют необходимые файлы: {missing_files}")
                return False
            
            # Проверяем импорт основных модулей
            test_imports = [
                "telegram", "aiohttp", "dotenv", "sqlalchemy"
            ]
            
            failed_imports = []
            for module in test_imports:
                try:
                    __import__(module)
                    logger.info(f"✅ Модуль {module} импортирован успешно")
                except ImportError:
                    logger.error(f"❌ Не удалось импортировать модуль {module}")
                    failed_imports.append(module)
            
            if failed_imports:
                logger.error(f"❌ Не удалось импортировать: {failed_imports}")
                return False
            
            logger.info("✅ Валидация установки пройдена успешно")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка валидации: {e}")
            return False
    
    def install(self) -> bool:
        """Основной метод установки"""
        logger.info("🚀 Начинаем установку модуля Support...")
        logger.info(f"📁 Директория модуля: {self.module_dir}")
        logger.info(f"🐍 Python executable: {self.python_executable}")
        
        try:
            # 1. Создаем .env файл если нужно
            if not self.create_env_file_if_missing():
                logger.warning("⚠️ Не удалось создать .env файл, продолжаем без него")
            
            # 2. Устанавливаем зависимости
            success, failed = self.install_missing_packages()
            if not success:
                logger.error(f"❌ Установка завершена с ошибками. Не установлены: {failed}")
                return False
            
            # 3. Валидируем установку
            if not self.validate_installation():
                logger.error("❌ Валидация установки не пройдена")
                return False
            
            logger.info("🎉 Установка модуля Support завершена успешно!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка установки: {e}")
            return False


class ProcessManager:
    """Класс для управления жизненным циклом процессов модулей"""
    
    @staticmethod
    def kill_existing_bot_processes():
        """Завершает все существующие процессы бота Support"""
        import psutil
        
        killed_processes = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info['cmdline']
                    if cmdline and any('Support' in arg and 'main.py' in arg for arg in cmdline):
                        logger.info(f"[Process Manager] 🔍 Найден процесс Support: PID {proc.info['pid']}")
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                            killed_processes.append(proc.info['pid'])
                            logger.info(f"[Process Manager] ✅ Процесс {proc.info['pid']} завершен")
                        except psutil.TimeoutExpired:
                            proc.kill()
                            killed_processes.append(proc.info['pid'])
                            logger.warning(f"[Process Manager] ⚠️ Принудительно завершен процесс {proc.info['pid']}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            logger.warning("[Process Manager] ⚠️ psutil не установлен, пропускаем проверку процессов")
            return []
        except Exception as e:
            logger.error(f"[Process Manager] ❌ Ошибка при поиске процессов: {e}")
            return []
        
        if killed_processes:
            logger.info(f"[Process Manager] 🎯 Завершено процессов: {len(killed_processes)}")
            import time
            time.sleep(2)  # Даем время на полное завершение
        
        return killed_processes
    
    @staticmethod
    def register_process(process_name: str, process: subprocess.Popen) -> None:
        """Регистрирует процесс для отслеживания"""
        global _module_processes, _process_lock
        
        with _process_lock:
            _module_processes[process_name] = process
            logger.info(f"[Process Manager] Зарегистрирован процесс: {process_name} (PID: {process.pid})")
    
    @staticmethod
    def unregister_process(process_name: str) -> None:
        """Удаляет процесс из отслеживания"""
        global _module_processes, _process_lock
        
        with _process_lock:
            if process_name in _module_processes:
                del _module_processes[process_name]
                logger.info(f"[Process Manager] Процесс {process_name} удален из отслеживания")
    
    @staticmethod
    def shutdown_all_processes() -> None:
        """Завершает все зарегистрированные процессы"""
        global _module_processes, _shutdown_event, _process_lock
        
        _shutdown_event.set()
        logger.info("[Process Manager] 🛑 Начато завершение всех модульных процессов...")
        
        with _process_lock:
            processes_to_shutdown = list(_module_processes.items())
        
        for process_name, process in processes_to_shutdown:
            try:
                if process and process.poll() is None:  # Процесс еще работает
                    logger.info(f"[Process Manager] 🔄 Завершение процесса {process_name} (PID: {process.pid})...")
                    
                    # Попробуем корректно завершить процесс
                    process.terminate()
                    
                    # Дадим время на корректное завершение
                    try:
                        process.wait(timeout=10)
                        logger.info(f"[Process Manager] ✅ Процесс {process_name} корректно завершен")
                    except subprocess.TimeoutExpired:
                        # Если не завершился корректно, принудительно убиваем
                        logger.warning(f"[Process Manager] ⚠️ Принудительное завершение процесса {process_name}")
                        process.kill()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            logger.error(f"[Process Manager] ❌ Не удалось завершить процесс {process_name}")
                else:
                    logger.info(f"[Process Manager] ℹ️ Процесс {process_name} уже завершен")
                            
            except Exception as e:
                logger.error(f"[Process Manager] ❌ Ошибка при завершении процесса {process_name}: {e}")
        
        with _process_lock:
            _module_processes.clear()
        
        logger.info("[Process Manager] ✅ Завершение всех процессов завершено")
    
    @staticmethod
    def setup_signal_handlers() -> None:
        """Настраивает обработчики сигналов для корректного завершения"""
        def signal_handler(signum, frame):
            logger.info(f"[Process Manager] 📡 Получен сигнал {signum}, завершение процессов...")
            ProcessManager.shutdown_all_processes()
            sys.exit(0)
        
        # Регистрируем обработчики сигналов
        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            
            # Для Windows
            if os.name == 'nt':
                signal.signal(signal.SIGBREAK, signal_handler)
            
            # Регистрируем функцию завершения при выходе
            atexit.register(ProcessManager.shutdown_all_processes)
            
            logger.info("[Process Manager] ✅ Обработчики сигналов настроены")
            
        except Exception as e:
            logger.error(f"[Process Manager] ❌ Ошибка настройки обработчиков сигналов: {e}")
    
    @staticmethod
    def is_shutdown_requested() -> bool:
        """Проверяет, был ли запрошен shutdown"""
        return _shutdown_event.is_set()
    
    @staticmethod
    def get_active_processes() -> Dict[str, subprocess.Popen]:
        """Возвращает словарь активных процессов"""
        global _module_processes, _process_lock
        
        with _process_lock:
            return _module_processes.copy()


def install_support_dependencies() -> bool:
    """
    Основная функция для установки зависимостей модуля Support.
    Вызывается автоматически при загрузке модуля.
    """
    try:
        logger.info("🔄 Автоматическая проверка зависимостей модуля Support...")
        
        # Создаем экземпляр установщика
        installer = SupportInstaller()
        
        # Запускаем установку
        success = installer.install()
        
        if success:
            logger.info("✅ Модуль Support готов к работе!")
            
            # Настраиваем обработчики сигналов для корректного завершения
            ProcessManager.setup_signal_handlers()
            
            return True
        else:
            logger.error("❌ Не удалось подготовить модуль Support")
            return False
            
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при подготовке модуля Support: {e}")
        return False


# Автоматическая установка при импорте модуля (только если запускается не как основной скрипт)
if __name__ != "__main__":
    # Запускаем установку зависимостей только при импорте
    install_success = install_support_dependencies()
    if not install_success:
        logger.warning("⚠️ Модуль Support может работать некорректно из-за проблем с зависимостями")


# Если файл запускается напрямую - запускаем только установку
if __name__ == "__main__":
    logger.info("📦 Запуск установщика модуля Support...")
    installer = SupportInstaller()
    success = installer.install()
    
    if success:
        print("✅ Установка завершена успешно!")
        exit(0)
    else:
        print("❌ Установка завершена с ошибками!")
        exit(1)

def install_support_dependencies() -> bool:
    """Публичная функция для установки зависимостей модуля Support"""
    # Настройка обработчиков сигналов при первом импорте
    ProcessManager.setup_signal_handlers()
    
    installer = SupportInstaller()
    return installer.install()


if __name__ == "__main__":
    # Настройка логирования для standalone запуска с ротацией
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler(
                'support_installer.log', 
                maxBytes=5*1024*1024,  # 5MB
                backupCount=2,
                encoding='utf-8'
            )
        ]
    )
    
    logger = logging.getLogger(__name__)
    
    logger.info("="*60)
    logger.info("🛠 Support Module Installer")
    logger.info("="*60)
    
    installer = SupportInstaller()
    success = installer.install()
    
    if success:
        logger.info("✅ Установка завершена успешно!")
        sys.exit(0)
    else:
        logger.error("❌ Установка завершена с ошибками!")
        sys.exit(1)
