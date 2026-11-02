#!/usr/bin/env python3
"""
Создание иконки icon.ico для SystemMonitor
"""

import os

from PIL import Image, ImageDraw


def create_icon():
    # Создаем изображение 256x256 (максимальный размер для ICO)
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    
    # Создаем список изображений для иконки
    images = []
    
    for width, height in sizes:
        # Создаем новое изображение
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Расчет отступов
        padding = max(4, width // 16)
        width - padding * 2
        height - padding * 2
        
        # Фон - темно-синий
        draw.rounded_rectangle(
            [(padding, padding), (width - padding - 1, height - padding - 1)],
            radius=max(2, width // 16),
            fill=(30, 40, 60, 255)
        )
        
        # Внутренний прямоугольник - синий
        draw.rounded_rectangle(
            [(padding + 2, padding + 2), (width - padding - 3, height - padding - 3)],
            radius=max(1, width // 20),
            fill=(50, 120, 200, 255)
        )
        
        # График (линии мониторинга)
        if width >= 32:
            # Линии графика
            bar_width = max(2, width // 12)
            bar_spacing = max(2, width // 10)
            
            start_x = padding + 4
            start_y = height - padding - 8
            
            # 4 столбика разной высоты
            for i in range(4):
                x = start_x + i * (bar_width + bar_spacing)
                bar_height = int((height - padding * 2 - 12) * [0.3, 0.7, 0.5, 0.9][i])
                y = start_y - bar_height
                draw.rectangle([x, y, x + bar_width - 1, start_y - 1], fill=(255, 255, 255, 255))
        
        images.append(img)
    
    # Сохраняем как ICO
    icon_path = "icon.ico"
    images[0].save(
        icon_path,
        format="ICO",
        sizes=[(w, h) for w, h in sizes],
        append_images=images[1:]
    )
    
    print(f"Иконка сохранена: {os.path.abspath(icon_path)}")
    return icon_path

if __name__ == "__main__":
    create_icon()
