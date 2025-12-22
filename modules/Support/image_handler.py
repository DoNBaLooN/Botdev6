import os
import logging
import re
from typing import List, Tuple, Dict, Optional
from telegram import Update, InputMediaPhoto
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

class ImageHandler:
    """Обработчик изображений для технической поддержки"""
    
    def __init__(self):
        self.images_dir = os.path.join(os.path.dirname(__file__), 'images')
        self.instruction_folders = {
            'happ': 'happ',
            'android_tv': 'android_tv', 
            'steam_deck': 'steam_deck',
            'oculus_quest': 'oculus_quest',
            'balance': 'balance',
            'coupon': 'coupon',
            'refresh': 'refresh',
            'windows_linux_macos_pc': 'windows_linux_macos_pc'
        }
    
    def validate_and_clean_html(self, text):
        """Валидация и очистка HTML для Telegram"""
        if not text:
            return ""
        
        import re
        
        # Убираем все HTML теги кроме разрешённых Telegram
        allowed_tags = ['b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del', 'code', 'pre', 'a', 'tg-spoiler', 'blockquote']
        
        # Паттерн для поиска всех HTML тегов
        tag_pattern = r'<(/?)(\w+)([^>]*)>'
        
        def replace_tag(match):
            is_closing = bool(match.group(1))
            tag_name = match.group(2).lower()
            attributes = match.group(3)
            
            # Если тег разрешён
            if tag_name in allowed_tags:
                if tag_name == 'a' and not is_closing and attributes:
                    # Для ссылок оставляем только href
                    href_match = re.search(r'href=["\']([^"\']*)["\']', attributes)
                    if href_match:
                        return f'<{match.group(1)}{tag_name} href="{href_match.group(1)}">'
                return f'<{match.group(1)}{tag_name}>'
            else:
                # Неразрешённый тег - убираем
                return ''
        
        # Заменяем все теги
        cleaned_text = re.sub(tag_pattern, replace_tag, str(text))
        
        # Убираем лишние пробелы и переводы строк
        cleaned_text = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned_text)
        cleaned_text = cleaned_text.strip()
        
        return cleaned_text
    
    def extract_image_requests(self, ai_response: str) -> Tuple[str, List[Dict[str, str]]]:
        """
        Извлекает запросы на отправку изображений из ответа ИИ
        
        Формат: [IMAGES:instruction_type:image1,image2,image3]
        Пример: [IMAGES:happ:step1,step2,step3] или [IMAGES:happ:all]
        
        Returns:
            Tuple[str, List[Dict]]: (очищенный_текст, список_изображений)
        """
        image_requests = []
        
        # Паттерн для поиска запросов изображений
        pattern = r'\[IMAGES:([^:]+):([^\]]+)\]'
        matches = re.findall(pattern, ai_response)
        
        for instruction_type, images_spec in matches:
            instruction_type = instruction_type.strip()
            images_spec = images_spec.strip()
            
            if instruction_type in self.instruction_folders:
                if images_spec.lower() == 'all':
                    # Отправить все изображения из папки
                    images = self._get_all_images_from_folder(instruction_type)
                else:
                    # Отправить конкретные изображения
                    image_names = [name.strip() for name in images_spec.split(',')]
                    images = self._get_specific_images(instruction_type, image_names)
                
                if images:
                    image_requests.extend(images)
        
        # Удаляем запросы изображений из текста
        cleaned_text = re.sub(pattern, '', ai_response).strip()
        
        return cleaned_text, image_requests
    
    def _get_all_images_from_folder(self, instruction_type: str) -> List[Dict[str, str]]:
        """Получает все изображения из папки инструкции"""
        folder_path = os.path.join(self.images_dir, self.instruction_folders[instruction_type])
        images = []
        
        if os.path.exists(folder_path):
            for filename in sorted(os.listdir(folder_path)):
                if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                    images.append({
                        'path': os.path.join(folder_path, filename),
                        'filename': filename,
                        'instruction_type': instruction_type
                    })
        
        return images
    
    def _get_specific_images(self, instruction_type: str, image_names: List[str]) -> List[Dict[str, str]]:
        """Получает конкретные изображения по именам"""
        folder_path = os.path.join(self.images_dir, self.instruction_folders[instruction_type])
        images = []
        
        if os.path.exists(folder_path):
            for image_name in image_names:
                # Поиск файла с учетом различных расширений
                found_file = None
                for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
                    potential_path = os.path.join(folder_path, f"{image_name}{ext}")
                    if os.path.exists(potential_path):
                        found_file = potential_path
                        break
                    
                    # Также проверяем, если уже указано расширение
                    if image_name.endswith(ext):
                        potential_path = os.path.join(folder_path, image_name)
                        if os.path.exists(potential_path):
                            found_file = potential_path
                            break
                
                if found_file:
                    images.append({
                        'path': found_file,
                        'filename': os.path.basename(found_file),
                        'instruction_type': instruction_type
                    })
                else:
                    logger.warning(f"Изображение не найдено: {image_name} в папке {instruction_type}")
        
        return images
    
    async def send_images_with_text(self, 
                                   update: Update, 
                                   context: ContextTypes.DEFAULT_TYPE, 
                                   text: str, 
                                   images: List[Dict[str, str]],
                                   reply_markup=None) -> bool:
        """
        Отправляет текст с изображениями
        
        Args:
            update: Telegram update
            context: Bot context
            text: Текст сообщения
            images: Список изображений для отправки
            reply_markup: Клавиатура для сообщения
            
        Returns:
            bool: True если отправка успешна
        """
        try:
            chat_id = update.effective_chat.id
            
            # Валидируем и очищаем HTML текст
            cleaned_text = self.validate_and_clean_html(text)
            
            if not images:
                # Если нет изображений, отправляем только текст
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=cleaned_text,
                        reply_markup=reply_markup,
                        parse_mode='HTML',
                        read_timeout=30,
                        write_timeout=30,
                        connect_timeout=30
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки сообщения с HTML: {e}")
                    # Попробуем без HTML
                    plain_text = cleaned_text.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '')
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=plain_text,
                        reply_markup=reply_markup,
                        read_timeout=30,
                        write_timeout=30,
                        connect_timeout=30
                    )
                return True
            
            if len(images) == 1:
                # Одно изображение - отправляем как фото с текстом и кнопками
                with open(images[0]['path'], 'rb') as photo:
                    try:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=photo,
                            caption=cleaned_text,
                            reply_markup=reply_markup,
                            parse_mode='HTML',
                            read_timeout=30,
                            write_timeout=30,
                            connect_timeout=30
                        )
                    except Exception as e:
                        logger.error(f"Ошибка отправки фото с HTML: {e}")
                        # Попробуем без HTML в caption
                        plain_caption = cleaned_text.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '')
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=photo,
                            caption=plain_caption,
                            reply_markup=reply_markup,
                            read_timeout=30,
                            write_timeout=30,
                            connect_timeout=30
                        )
            else:
                # Несколько изображений - сначала отправляем изображения
                max_images_per_group = 10
                
                for i in range(0, len(images), max_images_per_group):
                    image_group = images[i:i + max_images_per_group]
                    
                    media_group = []
                    for img in image_group:
                        with open(img['path'], 'rb') as photo:
                            media_group.append(
                                InputMediaPhoto(media=photo.read())
                            )
                    
                    await context.bot.send_media_group(
                        chat_id=chat_id,
                        media=media_group,
                        read_timeout=30,
                        write_timeout=30,
                        connect_timeout=30
                    )
                
                # Потом отправляем текст с кнопками
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=cleaned_text,
                        reply_markup=reply_markup,
                        parse_mode='HTML',
                        read_timeout=30,
                        write_timeout=30,
                        connect_timeout=30
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки текста с HTML: {e}")
                    # Попробуем без HTML
                    plain_text = cleaned_text.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '')
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=plain_text,
                        reply_markup=reply_markup,
                        read_timeout=30,
                        write_timeout=30,
                        connect_timeout=30
                    )
            
            logger.info(f"Отправлено {len(images)} изображений с текстом пользователю {update.effective_user.id}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при отправке изображений: {e}")
            # В случае ошибки отправляем только текст
            try:
                # Валидируем текст для fallback
                cleaned_text = self.validate_and_clean_html(text)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=cleaned_text,
                    reply_markup=reply_markup,
                    parse_mode='HTML',
                    read_timeout=30,
                    write_timeout=30,
                    connect_timeout=30
                )
            except Exception as e2:
                logger.error(f"Ошибка при отправке текста как fallback с HTML: {e2}")
                # Последняя попытка без HTML
                try:
                    plain_text = text.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '')
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=plain_text,
                        reply_markup=reply_markup,
                        read_timeout=30,
                        write_timeout=30,
                        connect_timeout=30
                    )
                except Exception as e3:
                    logger.error(f"Ошибка при отправке текста без HTML: {e3}")
                    return False
            return True
    
    def get_instruction_folders_info(self) -> str:
        """Возвращает информацию о папках с изображениями для документации"""
        info = []
        info.append("📁 **Структура папок для изображений:**")
        info.append("")
        
        for key, folder in self.instruction_folders.items():
            folder_path = os.path.join(self.images_dir, folder)
            image_count = 0
            if os.path.exists(folder_path):
                image_count = len([f for f in os.listdir(folder_path) 
                                 if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))])
            
            info.append(f"• `{folder}/` - для инструкций типа '{key}' ({image_count} изображений)")
        
        info.append("")
        info.append("📋 **Как GigaChat может запросить изображения:**")
        info.append("• `[IMAGES:happ:all]` - все изображения из папки happ")
        info.append("• `[IMAGES:happ:step1,step2]` - конкретные изображения step1 и step2 из папки happ")
        info.append("• `[IMAGES:android_tv:setup,config]` - изображения setup и config из папки android_tv")
        
        return "\n".join(info)
