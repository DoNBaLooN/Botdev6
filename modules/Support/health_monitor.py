"""
Мониторинг здоровья модуля технической поддержки
Включает проверки памяти, соединений и производительности
"""

import asyncio
import logging
import psutil
import gc
from datetime import datetime, timedelta
from typing import Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class HealthMonitor:
    """Монитор здоровья системы поддержки"""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.memory_warnings = 0
        self.max_memory_mb = 1024  # Увеличиваем лимит с 512MB до 1GB
        self.stats_file = Path("health_stats.log")
        
    def get_memory_usage(self) -> Dict[str, float]:
        """Получение информации об использовании памяти"""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            
            return {
                'rss_mb': memory_info.rss / 1024 / 1024,  # Реальная память
                'vms_mb': memory_info.vms / 1024 / 1024,  # Виртуальная память
                'percent': process.memory_percent(),       # Процент от общей памяти
                'available_mb': psutil.virtual_memory().available / 1024 / 1024
            }
        except Exception as e:
            logger.error(f"Failed to get memory usage: {e}")
            return {}
    
    def get_system_stats(self) -> Dict[str, any]:
        """Получение системной статистики"""
        try:
            return {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'disk_usage': psutil.disk_usage('.').percent,
                'uptime_hours': (datetime.now() - self.start_time).total_seconds() / 3600,
                'active_connections': len(psutil.net_connections()),
                'gc_objects': len(gc.get_objects())
            }
        except Exception as e:
            logger.error(f"Failed to get system stats: {e}")
            return {}
    
    def check_memory_health(self) -> bool:
        """Проверка здоровья памяти с улучшенной логикой"""
        memory = self.get_memory_usage()
        if not memory:
            return False
        
        current_memory_mb = memory.get('rss_mb', 0)
        
        if current_memory_mb > self.max_memory_mb:
            self.memory_warnings += 1
            logger.warning(f"⚠️ High memory usage: {current_memory_mb:.1f}MB (limit: {self.max_memory_mb}MB) - warning #{self.memory_warnings}")
            
            # ИСПРАВЛЕНИЕ: Увеличиваем порог и добавляем cleanup вместо критического завершения
            if self.memory_warnings > 8:  # Увеличено с 5 до 8
                logger.critical("🚨 Memory usage consistently high - performing emergency cleanup!")
                
                # Выполняем принудительную очистку
                self.perform_cleanup()
                
                # Дополнительная очистка объектов
                import gc
                collected = gc.collect()
                logger.info(f"🧹 Emergency cleanup: собрано {collected} объектов")
                
                # Сбрасываем счетчик после очистки
                self.memory_warnings = max(0, self.memory_warnings - 3)
                
                # НЕ возвращаем False - система продолжает работать
                logger.info("🔄 System continues after cleanup")
                return True  # ИСПРАВЛЕНИЕ: Продолжаем работу вместо критического завершения
        else:
            # Постепенно снижаем счетчик предупреждений при нормальном потреблении
            self.memory_warnings = max(0, self.memory_warnings - 1)
        
        return True
    
    def perform_cleanup(self):
        """Улучшенная очистка памяти для предотвращения object leak"""
        try:
            logger.info("🧹 Начинаем агрессивную очистку памяти...")
            
            # Множественная сборка мусора для лучшей очистки
            total_collected = 0
            for i in range(3):  # 3 прохода сборки мусора
                collected = gc.collect()
                total_collected += collected
                if collected > 0:
                    logger.debug(f"GC pass {i+1}: собрано {collected} объектов")
            
            logger.info(f"🗑️ Всего собрано объектов: {total_collected}")
            
            # Принудительная очистка кэшей модулей
            try:
                # Очищаем кэш импортированных модулей (осторожно!)
                import sys
                temp_modules = [name for name in sys.modules.keys() if 'temp_' in name or '_cache' in name]
                for module_name in temp_modules:
                    if module_name in sys.modules:
                        del sys.modules[module_name]
                        
                if temp_modules:
                    logger.info(f"🧽 Очищены кэшированные модули: {len(temp_modules)}")
                    
            except Exception as cache_error:
                logger.warning(f"Ошибка очистки кэшей: {cache_error}")
            
            # Дополнительная очистка для Python объектов
            try:
                # Вызываем gc.collect() еще раз после очистки кэшей
                final_collected = gc.collect()
                logger.info(f"🏁 Финальная очистка: {final_collected} объектов")
                
                # Логируем текущее состояние памяти после очистки
                memory_after = self.get_memory_usage()
                if memory_after:
                    logger.info(f"📊 Память после очистки: {memory_after.get('rss_mb', 0):.1f}MB")
                    
            except Exception as final_error:
                logger.warning(f"Ошибка финальной очистки: {final_error}")
                
        except Exception as e:
            logger.error(f"❌ Cleanup failed: {e}")
    
    def log_health_status(self):
        """Запись статуса здоровья в лог с автоочисткой"""
        try:
            memory = self.get_memory_usage()
            system = self.get_system_stats()
            
            status_msg = (
                f"Health Status: "
                f"Memory: {memory.get('rss_mb', 0):.1f}MB, "
                f"CPU: {system.get('cpu_percent', 0):.1f}%, "
                f"Uptime: {system.get('uptime_hours', 0):.1f}h, "
                f"Objects: {system.get('gc_objects', 0)}"
            )
            
            logger.info(status_msg)
            
            # Проверяем размер файла статистики и очищаем если нужно
            if self.stats_file.exists():
                file_size_mb = self.stats_file.stat().st_size / 1024 / 1024
                if file_size_mb > 10:  # Если файл больше 10MB
                    # Переименовываем старый файл
                    backup_name = f"health_stats_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
                    self.stats_file.rename(backup_name)
                    logger.info(f"🗂️ Health stats file archived: {backup_name}")
            
            # Записываем в файл статистики
            with open(self.stats_file, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now().isoformat()} - {status_msg}\n")
                
        except Exception as e:
            logger.error(f"Failed to log health status: {e}")
    
    async def health_check_cycle(self, interval_minutes: int = 10):
        """Цикл проверки здоровья системы"""
        while True:
            try:
                # Проверяем память
                memory_ok = self.check_memory_health()
                
                # Логируем статус
                self.log_health_status()
                
                # Если память плохо - выполняем очистку
                if not memory_ok:
                    self.perform_cleanup()
                
                # Ждем до следующей проверки
                await asyncio.sleep(interval_minutes * 60)
                
            except Exception as e:
                logger.error(f"Health check cycle error: {e}")
                await asyncio.sleep(60)  # При ошибке ждем минуту
    
    def get_health_report(self) -> Dict[str, any]:
        """Получение полного отчета о здоровье"""
        memory = self.get_memory_usage()
        system = self.get_system_stats()
        
        return {
            'timestamp': datetime.now().isoformat(),
            'uptime_hours': system.get('uptime_hours', 0),
            'memory_usage_mb': memory.get('rss_mb', 0),
            'memory_percent': memory.get('percent', 0),
            'cpu_percent': system.get('cpu_percent', 0),
            'memory_warnings': self.memory_warnings,
            'gc_objects': system.get('gc_objects', 0),
            'disk_usage_percent': system.get('disk_usage', 0),
            'status': 'healthy' if self.memory_warnings < 5 else 'warning' if self.memory_warnings < 10 else 'critical'
        }

# Глобальный экземпляр монитора
health_monitor = HealthMonitor()
