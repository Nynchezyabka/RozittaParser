import os
import re
import subprocess
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).parent

# Регулярка для поиска импортов
IMPORT_RE = re.compile(r'^\s*(?:from|import)\s+([a-zA-Z0-9_\.]+)')

# Цвета для разных слоёв
COLORS = {
    'core': '#a8e6cf',
    'auth': '#ffaaa5',
    'chats': '#ff8b94',
    'parser': '#c7e9c0',
    'export': '#b5f2e8',
    'ui': '#ffcc88',
    'main': '#d3d3d3',
    'other': '#e0e0e0'
}

def get_color(folder):
    if 'core' in folder.split(os.sep):
        return COLORS['core']
    if 'ui' in folder.split(os.sep):
        return COLORS['ui']
    if folder == 'main.py':
        return COLORS['main']
    for key in ['auth', 'chats', 'parser', 'export']:
        if key in folder:
            return COLORS[key]
    return COLORS['other']

def find_imports(file_path):
    imports = set()
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                match = IMPORT_RE.match(line)
                if match:
                    module = match.group(1).split('.')[0]
                    imports.add(module)
    except:
        pass
    return imports

def main():
    # Собираем все .py файлы, исключая этот скрипт
    py_files = []
    for root, dirs, files in os.walk(PROJECT_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('venv', 'env', '__pycache__')]
        for file in files:
            if file.endswith('.py') and file != 'generate_map.py':
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, PROJECT_DIR).replace('\\', '/')
                py_files.append((full_path, rel_path))

    print(f"Найдено {len(py_files)} файлов. Анализируем импорты...")

    # Словарь: файл -> множество импортов (только те, что есть в проекте)
    file_imports = {}
    for full_path, rel_path in py_files:
        imports = find_imports(full_path)
        local = set()
        for imp in imports:
            # Проверяем, есть ли такой модуль среди файлов проекта
            for other_full, other_rel in py_files:
                other_module = other_rel.replace('/', '.')
                if other_module.startswith(imp) or other_module == imp or imp == other_module.split('.')[0]:
                    local.add(imp)
                    break
        file_imports[rel_path] = local

    # Группируем файлы по папкам
    folder_files = defaultdict(list)
    for rel_path in file_imports:
        if rel_path == 'main.py':
            folder = 'main.py'
        else:
            folder = os.path.dirname(rel_path)
            if not folder:
                folder = '.'
        folder_files[folder].append(rel_path)

    # Строим зависимости между папками
    folder_edges = defaultdict(set)
    for src_file, imports in file_imports.items():
        src_folder = src_file if src_file == 'main.py' else os.path.dirname(src_file) or '.'
        for imp in imports:
            for dst_file in file_imports:
                if dst_file.startswith(imp.replace('.', '/')) or dst_file == imp:
                    dst_folder = dst_file if dst_file == 'main.py' else os.path.dirname(dst_file) or '.'
                    if src_folder != dst_folder:
                        folder_edges[src_folder].add(dst_folder)

    # Генерация DOT-файла
    dot_path = PROJECT_DIR / 'map.dot'
    with open(dot_path, 'w', encoding='utf-8') as f:
        f.write('digraph G {\n')
        f.write('    rankdir=LR;\n')
        f.write('    node [shape=box, style=filled];\n')
        all_folders = set(folder_edges.keys()) | {d for edges in folder_edges.values() for d in edges}
        for folder in all_folders:
            color = get_color(folder)
            f.write(f'    "{folder}" [fillcolor="{color}"];\n')
        for src, dst_set in folder_edges.items():
            for dst in dst_set:
                f.write(f'    "{src}" -> "{dst}";\n')
        f.write('}\n')

    print(f"DOT-файл сохранён: {dot_path}")

    # Конвертируем в PNG
    png_path = PROJECT_DIR / 'map.png'
    try:
        subprocess.run(['dot', '-Tpng', str(dot_path), '-o', str(png_path)], check=True)
        print(f"✅ Карта создана: {png_path}")
    except FileNotFoundError:
        print("❌ dot не найден. Убедитесь, что Graphviz установлен и добавлен в PATH.")
    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == '__main__':
    main()