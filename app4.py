import os
from config import Config
from flask import Flask, render_template, request, send_file, redirect, url_for, jsonify
import csv
import time
import threading
import requests
import json
import pandas as pd
from contextlib import contextmanager
from mp_api.client import MPRester
from pymatgen.core.periodic_table import Element
from pymatgen.core.composition import Composition
from flask_cors import CORS
from dotenv import load_dotenv
load_dotenv()
import signal
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})  # 允许所有来源访问 /api/*

app.config.from_object(Config)
app.secret_key = "123"  # 用于会话管理

# 后端预设的API Key（请替换为您自己的有效API Key）
BACKEND_API_KEY = os.getenv("BACKEND_API_KEY")   # 替换为您的Materials Project API密钥
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY") # 替换为您的DeepSeek API密钥
DEEPSEEK_ENDPOINT = "https://api.deepseek.com/v1/chat/completions"

# 配置参数
DEFAULT_ELEMENT = "Ti"  # 默认查询元素
DEFAULT_MAX_RECORDS = 100  # 降低默认记录数，避免超时
RATE_LIMIT_DELAY = 0.5  # API请求间隔
RESULTS_FOLDER = "results"  # 结果保存目录

# 初始化文件夹
os.makedirs(RESULTS_FOLDER, exist_ok=True)

# 使用API支持的所有字段（根据错误信息中的可用字段列表）
FIELDS = [
    # 基本标识信息
    "material_id",
    "formula_pretty",
    "formula_anonymous",
    "elements",
    "nelements",
    "composition",
    "composition_reduced",
    "chemsys",  # 替代 composition_hill

    # 结构信息
    "structure",
    "volume",
    "density",
    "density_atomic",
    "symmetry",
    "nsites",  # 替代 crystal_system
    "last_updated",

    # 热力学性质
    "energy_above_hull",
    "is_stable",
    "formation_energy_per_atom",
    "equilibrium_reaction_energy_per_atom",
    "decomposes_to",
    "energy_per_atom",  # 替代 total_energy

    # 电子性质
    "band_gap",
    "efermi",
    "is_gap_direct",
    "is_metal",
    "ordering",
    "is_magnetic",
    "total_magnetization",
    "total_magnetization_normalized_vol",
    "total_magnetization_normalized_formula_unit",
    "num_magnetic_sites",
    "num_unique_magnetic_sites",
    "types_of_magnetic_species",

    # 力学性质
    "bulk_modulus",
    "shear_modulus",
    "universal_anisotropy",
    "homogeneous_poisson",

    # 其他性质
    "task_ids",
    "has_props",
    "theoretical",
    "database_IDs"
]

# 自定义异常类
class QueryTimeoutError(Exception):
    pass

# 超时上下文管理器
@contextmanager
def timeout(seconds):
    def handler(signum, frame):
        raise QueryTimeoutError(f"查询超时 ({seconds}秒)")

    # Windows不支持signal.SIGALRM
    if os.name != 'nt':
        # Unix系统使用信号
        original_handler = signal.signal(signal.SIGALRM, handler)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, original_handler)
    else:
        # Windows使用线程计时器
        timer = threading.Timer(seconds, lambda: threading.current_thread().raise_exception())
        timer.start()
        try:
            yield
        finally:
            timer.cancel()

@app.route('/', methods=['GET', 'POST'])
def index():
    error = None
    if request.method == 'POST':
        element = request.form.get('element', DEFAULT_ELEMENT).strip()
        max_records = request.form.get('max_records', DEFAULT_MAX_RECORDS)

        try:
            max_records = int(max_records)
            max_records = min(max_records, 500)
        except ValueError:
            error = "记录数必须是整数"
            return render_template('index.html',
                                   error=error,
                                   default_element=DEFAULT_ELEMENT,
                                   default_max_records=DEFAULT_MAX_RECORDS)

        if not element:
            error = "请输入有效元素符号"
        elif max_records < 1 or max_records > 500:
            error = "记录数需在1-500之间"
        else:
            try:
                with timeout(60):
                    data = fetch_element_data(element, max_records, BACKEND_API_KEY)

                if not data:
                    error = "未找到相关数据"
                else:
                    filename = save_to_csv(data, element)
                    return redirect(url_for('download_file', filename=filename))
            except QueryTimeoutError as e:
                error = f"查询超时: {str(e)}"
            except Exception as e:
                error = f"发生错误: {str(e)}"

    return render_template('index.html',
                           error=error,
                           default_element=DEFAULT_ELEMENT,
                           default_max_records=DEFAULT_MAX_RECORDS)




#@app.route('/api/chat', methods=['POST'])
#def chat():
#    try:
        # 1. 解析请求数据
#        data = request.get_json()
#        query = data.get('query', '默认查询内容')

        # 2. 构造DeepSeek API请求
#        headers = {
#            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
#            "Content-Type": "application/json"
#        }
#        payload = {
#            "model": "deepseek-chat",  # 根据实际模型调整
#            "messages": [{"role": "user", "content": query}]
#        }

        # 3. 发送请求到DeepSeek
#        response = requests.post(
#            DEEPSEEK_ENDPOINT,
#            headers=headers,
#            json=payload,
#            timeout=60  # 设置超时时间
#        )
#        response.raise_for_status()  # 自动抛出HTTP错误

        # 4. 返回处理结果
 #       return jsonify(response.json())

#    except requests.exceptions.RequestException as e:
#        # 网络错误处理
#        return jsonify({"error": f"请求失败: {str(e)}"}), 500
#    except Exception as e:
        # 其他错误处理
#        return jsonify({"error": f"内部错误: {str(e)}"}), 500
@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        query = data.get('query', '默认查询内容')

        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
        payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": query}]}
        response = requests.post(DEEPSEEK_ENDPOINT, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        return jsonify(response.json())  # 直接返回原始 JSON

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"请求失败: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"内部错误: {str(e)}"}), 500
import re

def call_deepseek_api(message):
    # 定义模型映射规则
    model_mapping = {
        "coder": r"(写代码|调试代码|python|java|c\+\+|算法|数据结构|爬虫|脚本)",
        "researcher": r"(数据分析|统计|可视化|机器学习|深度学习|预测模型|实验设计)",
        "answer": r"(默认|其他|.*)"
    }

    # 自动识别问题类型
    selected_model = "answer"
    for model, pattern in model_mapping.items():
        if re.search(pattern, message, re.IGNORECASE):
            selected_model = model
            break

    # 根据模型选择调整提示词
    system_prompt = {
        "coder": "你是一个专业代码生成助手，擅长编写高质量代码并提供调试建议。",
        "researcher": "你是一位数据科学家，专注于数据分析、机器学习和实验设计。",
        "answer": "你是一个通用智能助手，能回答各种领域的问题。"
    }[selected_model]

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": f"deepseek-{selected_model}",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ],
        "temperature": 0.7,
        "max_tokens": 2000
    }

    try:
        response = requests.post(
            DEEPSEEK_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        return result.get("choices", [{}])[0].get("message", {}).get("content", "")
    except requests.exceptions.RequestException as e:
        return f"请求失败: {str(e)}"
    except KeyError as e:
        return f"模型未找到或权限不足，请检查API配置: {str(e)}"
@app.route('/download/<filename>')
def download_file(filename):
    file_path = os.path.join(RESULTS_FOLDER, filename)
    if not os.path.exists(file_path):
        return "文件不存在", 404

    response = send_file(file_path, as_attachment=True)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route('/api/materials/predict', methods=['POST'])
def predict_material():
    data = request.get_json()
    if not data:
        return jsonify({"error": "无效请求数据"}), 400

    try:
        prediction = deepseek_material_prediction(data)
        return jsonify({"prediction": prediction}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/materials/analyze', methods=['POST'])
def analyze_material():
    if 'file' not in request.files:
        return jsonify({"error": "未检测到上传文件"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "文件名为空"}), 400

    if file and allowed_file(file.filename):
        try:
            # 读取文件内容（二进制模式）
            file_content = file.read()
            # 调用分析函数（已实现）
            analysis = deepseek_material_analysis(file_content)
            return jsonify({"status": "success", "data": analysis}), 200
        except NameError as e:
            return jsonify({"error": f"函数未定义：{str(e)}"}), 500  # 提示缺失的函数
        except Exception as e:
            return jsonify({"error": f"分析失败：{str(e)}"}), 500
    else:
        return jsonify({"error": "不支持的文件格式（仅CSV/Excel）"}), 400

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'csv', 'xlsx'}

def fetch_element_data(element, max_records, api_key):
    all_data = []
    print(f"=== 开始查询元素: {element} (限制{max_records}条) ===")
    start_time = time.time()

    with MPRester(api_key=api_key) as mpr:
        try:
            results = mpr.materials.summary.search(
                elements=[element],
                fields=FIELDS,
                chunk_size=min(100, max_records),
                num_chunks=(max_records + 99) // 100
            )

            results = list(results)[:max_records]
            total_results = len(results)
            print(f"API返回的记录数: {total_results}")

            count = 0
            for doc in results:
                try:
                    lattice_a = lattice_b = lattice_c = None
                    sites = []
                    if doc.structure:
                        lattice = doc.structure.lattice
                        lattice_a, lattice_b, lattice_c = lattice.a, lattice.b, lattice.c

                        sites = []
                        for site in doc.structure.sites:
                            species_str = site.species_string
                            site_info = {
                                "species": species_str,
                                "coords": [float(c) for c in site.frac_coords],
                                "magmom": getattr(site.properties, "magmom", None)
                            }
                            sites.append(site_info)

                    elements_list = []
                    for el in doc.elements:
                        elements_list.append(str(el))

                    symmetry_info = {}
                    if hasattr(doc, 'symmetry') and doc.symmetry:
                        symmetry_info = {
                            "symbol": getattr(doc.symmetry, 'symbol', None),
                            "number": getattr(doc.symmetry, 'number', None),
                            "point_group": getattr(doc.symmetry, 'point_group', None)
                        }

                    data_row = {
                        "material_id": getattr(doc, 'material_id', ''),
                        "formula_pretty": getattr(doc, 'formula_pretty', ''),
                        "formula_anonymous": getattr(doc, 'formula_anonymous', ''),
                        "elements": ", ".join(elements_list),
                        "nelements": getattr(doc, 'nelements', ''),
                        "composition": str(getattr(doc, 'composition', '')),
                        "composition_reduced": str(getattr(doc, 'composition_reduced', '')),
                        "chemsys": getattr(doc, 'chemsys', ''),
                        "structure_lattice_a": lattice_a,
                        "structure_lattice_b": lattice_b,
                        "structure_lattice_c": lattice_c,
                        "structure_sites": str(sites),
                        "volume": getattr(doc, 'volume', ''),
                        "density": getattr(doc, 'density', ''),
                        "density_atomic": getattr(doc, 'density_atomic', ''),
                        "symmetry": str(symmetry_info),
                        "nsites": getattr(doc, 'nsites', ''),
                        "last_updated": str(getattr(doc, 'last_updated', '')),
                        "energy_above_hull": getattr(doc, 'energy_above_hull', ''),
                        "is_stable": getattr(doc, 'is_stable', ''),
                        "formation_energy_per_atom": getattr(doc, 'formation_energy_per_atom', ''),
                        "equilibrium_reaction_energy_per_atom": getattr(doc, 'equilibrium_reaction_energy_per_atom', ''),
                        "decomposes_to": str(getattr(doc, 'decomposes_to', '')),
                        "energy_per_atom": getattr(doc, 'energy_per_atom', ''),
                        "band_gap": getattr(doc, 'band_gap', ''),
                        "efermi": getattr(doc, 'efermi', ''),
                        "is_gap_direct": getattr(doc, 'is_gap_direct', ''),
                        "is_metal": getattr(doc, 'is_metal', ''),
                        "ordering": getattr(doc, 'ordering', ''),
                        "is_magnetic": getattr(doc, 'is_magnetic', ''),
                        "total_magnetization": getattr(doc, 'total_magnetization', ''),
                        "total_magnetization_normalized_vol": getattr(doc, 'total_magnetization_normalized_vol', ''),
                        "total_magnetization_normalized_formula_unit": getattr(doc, 'total_magnetization_normalized_formula_unit', ''),
                        "num_magnetic_sites": getattr(doc, 'num_magnetic_sites', ''),
                        "num_unique_magnetic_sites": getattr(doc, 'num_unique_magnetic_sites', ''),
                        "types_of_magnetic_species": str(getattr(doc, 'types_of_magnetic_species', '')),
                        "bulk_modulus": getattr(doc, 'bulk_modulus', ''),
                        "shear_modulus": getattr(doc, 'shear_modulus', ''),
                        "universal_anisotropy": getattr(doc, 'universal_anisotropy', ''),
                        "homogeneous_poisson": getattr(doc, 'homogeneous_poisson', ''),
                        "task_ids": str(getattr(doc, 'task_ids', '')),
                        "has_props": str(getattr(doc, 'has_props', '')),
                        "theoretical": getattr(doc, 'theoretical', ''),
                        "database_IDs": str(getattr(doc, 'database_IDs', ''))
                    }

                    all_data.append(data_row)
                    count += 1

                    if count % 10 == 0:
                        elapsed = time.time() - start_time
                        print(f"已处理 {count}/{total_results} 条记录 | 用时: {elapsed:.1f}秒", end='\r')

                    if count >= max_records:
                        print(f"\n=== 已达到最大记录数({max_records}) ===")
                        break
                except Exception as e:
                    print(f"\n处理记录时出错: {str(e)}")
                    continue

            elapsed = time.time() - start_time
            print(f"\n=== 成功获取 {len(all_data)} 条{element}化合物数据 | 总用时: {elapsed:.1f}秒 ===")
            return all_data

        except Exception as e:
            print(f"\n=== 查询{element}时发生错误 ===")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误详情: {str(e)}")
            raise e

def save_to_csv(data, element):
    if not data:
        print("⚠️ 未获取到有效数据，跳过CSV写入")
        return None

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{element}_compounds_{timestamp}.csv"
    filepath = os.path.join(RESULTS_FOLDER, filename)

    fieldnames = list(data[0].keys()) if data else []
    try:
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for row in data:
                cleaned_row = {k: str(v).replace('\n', ' ') if isinstance(v, str) else v for k, v in row.items()}
                writer.writerow(cleaned_row)

        print(f"=== 数据已保存到: {os.path.abspath(filepath)} ===")
        return filename
    except Exception as e:
        print(f"写入CSV失败: {str(e)}")
        raise e

# Windows线程异常辅助类
class RaiseExceptionInThread:
    def __init__(self, exc_class=SystemExit):
        self.exc_class = exc_class

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def raise_exception(self):
        raise self.exc_class()

# 修补Windows线程支持
if os.name == 'nt':
    threading.Thread.raise_exception = lambda self: RaiseExceptionInThread()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)