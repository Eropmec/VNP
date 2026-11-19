extends RefCounted
## Строки интерфейса игры. Язык — язык текста игры; нет перевода — по-русски.
## Этап 6 (темы интерфейса) позволит переопределять их в проекте.

const TEXT := {
	"ru": {
		"new_game": "Новая игра", "continue": "Продолжить", "load": "Загрузить", "save": "Сохранить",
		"settings": "Настройки", "quit": "Выход", "resume": "Вернуться в игру", "history": "История",
		"main_menu": "Главное меню", "back": "Назад", "restart": "Начать заново", "auto": "Авто",
		"empty_slot": "Пусто", "autosave": "Автосохранение", "quicksave": "Быстрое сохранение",
		"page": "Страница", "saved": "Сохранено", "loaded": "Загружено", "no_save": "Сохранений пока нет",
		"vol_master": "Общая громкость", "vol_music": "Музыка", "vol_sfx": "Звуки", "vol_voice": "Голос",
		"text_speed": "Скорость текста", "instant": "мгновенно", "auto_delay": "Пауза в авто-режиме",
		"fullscreen": "Во весь экран", "language": "Язык", "seconds": "с",
		"ending": "Концовка", "ending_good": "Хорошая концовка", "ending_bad": "Плохая концовка",
		"ending_secret": "Тайная концовка", "endings_found": "Найдено концовок",
		"save_missing": "Место из сохранения пропало из игры (обновление?) — начинаем с ближайшего узла",
		"confirm_menu": "Выйти в меню? Несохранённый прогресс останется в автосохранении.",
		"playtime": "в игре",
	},
	"en": {
		"new_game": "New game", "continue": "Continue", "load": "Load", "save": "Save",
		"settings": "Settings", "quit": "Quit", "resume": "Resume", "history": "History",
		"main_menu": "Main menu", "back": "Back", "restart": "Start over", "auto": "Auto",
		"empty_slot": "Empty", "autosave": "Autosave", "quicksave": "Quicksave",
		"page": "Page", "saved": "Saved", "loaded": "Loaded", "no_save": "No saves yet",
		"vol_master": "Master volume", "vol_music": "Music", "vol_sfx": "Sounds", "vol_voice": "Voice",
		"text_speed": "Text speed", "instant": "instant", "auto_delay": "Auto mode delay",
		"fullscreen": "Fullscreen", "language": "Language", "seconds": "s",
		"ending": "Ending", "ending_good": "Good ending", "ending_bad": "Bad ending",
		"ending_secret": "Secret ending", "endings_found": "Endings found",
		"save_missing": "The saved place no longer exists (game updated?) — continuing from the nearest node",
		"confirm_menu": "Return to the main menu? Progress is kept in the autosave.",
		"playtime": "played",
	},
}


static func t(key: String, lang: String) -> String:
	var table: Dictionary = TEXT.get(lang.substr(0, 2), TEXT["ru"])
	return table.get(key, TEXT["ru"].get(key, key))
