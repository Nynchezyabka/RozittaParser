import os
import re
from pathlib import Path

# Папка проекта
PROJECT_DIR = Path(__file__).parent

# Регулярное выражение для поиска импортов
IMPORT_RE = re.compile(r'^\s*(?:from|import)\s+([a-zA-Z0-9_\.]+)')

def find_imports(file_path):
    """Возвращает множество имён модулей, импортированных в файле"""
    imports = set()
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                match = IMPORT_RE.match(line)
                if match:
                    module = match.group(1).split('.')[0]  # берём только первый компонент
                    imports.add(module)
    except Exception:
        pass
    return imports

def main():
    # Собираем все .py файлы в проекте (исключая скрипт генерации)
    py_files = []
    for root, dirs, files in os.walk(PROJECT_DIR):
        # Пропускаем скрытые папки и папки виртуального окружения
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('venv', 'env', '__pycache__')]
        for file in files:
            if file.endswith('.py') and file != 'generate_graph.py':
                full_path = os.path.join(root, file)
                # Относительный путь для подписи на карте
                rel_path = os.path.relpath(full_path, PROJECT_DIR).replace('\\', '/')
                py_files.append((full_path, rel_path))

    # Строим граф
    print(f"Найдено {len(py_files)} файлов. Анализируем импорты...")
    edges = []
    nodes = set()

    for full_path, rel_path in py_files:
        module_name = rel_path.replace('/', '.')  # превращаем путь в имя модуля
        nodes.add(module_name)
        imports = find_imports(full_path)
        for imp in imports:
            # Ищем, какой файл соответствует этому импорту
            for other_full, other_rel in py_files:
                other_module = other_rel.replace('/', '.')
                if other_module.startswith(imp) or other_module == imp:
                    edges.append((module_name, other_module))
                    break

    # Пишем DOT-файл
    dot_path = PROJECT_DIR / 'dependencies.dot'
    with open(dot_path, 'w', encoding='utf-8') as f:
        f.write('digraph G {\n')
        f.write('    rankdir=LR;\n')  # слева направо
        f.write('    node [shape=box, style=filled, fillcolor=lightblue];\n')
        for src, dst in edges:
            if src != dst:
                f.write(f'    "{src}" -> "{dst}";\n')
        f.write('}\n')

    print(f"DOT-файл сохранён: {dot_path}")
    print("Теперь выполните команду: dot -Tpng dependencies.dot -o dependencies.png")

if __name__ == '__main__':
    main()