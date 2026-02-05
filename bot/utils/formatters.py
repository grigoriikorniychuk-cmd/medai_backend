from typing import Dict, Any

# Функция для форматирования результатов анализа
def format_analysis_results(analysis_results: Dict[str, Any]) -> str:
    """
    Форматирует результаты анализа звонка в читаемый вид
    
    Args:
        analysis_results: Словарь с результатами анализа
        
    Returns:
        Отформатированный текст для отправки пользователю
    """
    formatted_text = "<b>Результаты анализа звонка:</b>\n\n"
    
    # Проверяем наличие различных полей в результатах и добавляем их
    if "summary" in analysis_results:
        formatted_text += f"<b>Резюме:</b>\n{analysis_results['summary']}\n\n"
    
    if "sentiment" in analysis_results:
        sentiment = analysis_results["sentiment"]
        sentiment_emoji = "😃" if sentiment > 0.5 else "😐" if sentiment > 0.3 else "😞"
        formatted_text += f"<b>Эмоциональная окраска:</b> {sentiment_emoji} {sentiment:.2f}\n\n"
    
    if "key_points" in analysis_results and analysis_results["key_points"]:
        formatted_text += "<b>Ключевые моменты:</b>\n"
        for point in analysis_results["key_points"]:
            formatted_text += f"• {point}\n"
        formatted_text += "\n"
    
    if "recommendations" in analysis_results and analysis_results["recommendations"]:
        formatted_text += "<b>Рекомендации:</b>\n"
        for rec in analysis_results["recommendations"]:
            formatted_text += f"• {rec}\n"
        formatted_text += "\n"
    
    # Если результатов анализа нет или они неожиданного формата
    if len(formatted_text) < 50:
        formatted_text += "Данные анализа недоступны или в неожиданном формате.\n"
        formatted_text += f"Сырые данные: {str(analysis_results)[:500]}...\n"
    
    return formatted_text 