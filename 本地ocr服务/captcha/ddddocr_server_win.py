"""
ddddocr 本地点选验证码识别 HTTP 服务（高准确率版）

=== 与 ddddocr_server.py 的唯一差异 ===
仅修改 _scan_fonts() 以支持 Windows 字体路径。
其他逻辑（检测/OCR 集成/HOG/全排列/距离约束/HTTP 接口）完全保留。

字体扫描策略：
  - Windows: C:\\Windows\\Fonts\\*.{ttf,ttc,otf}，按关键字白名单 + 宽度法验证
  - macOS:   保留原 /System/Library/Fonts/** 逻辑
  - Linux:   /usr/share/fonts, ~/.fonts（思源/Noto）
  - 自定义:  环境变量 CAPTCHA_FONT_DIR 指向额外目录

接口:
  POST /click
  Body: {"image": "<base64>", "remark": "大中小"}
  Response: {"success": true, "data": {"result": "x1,y1|x2,y2|x3,y3"}}
"""

import base64
import io
import logging
import os
import platform
import sys
import time
from collections import Counter
from itertools import permutations

import cv2
import numpy as np
from flask import Flask, request, jsonify
from PIL import Image, ImageDraw, ImageFont

import ddddocr

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
log = logging.getLogger('ddddocr-server')

# ── 模型 ──────────────────────────────────────────────────────────
log.info('正在加载 ddddocr 模型...')
_det = ddddocr.DdddOcr(det=True, ocr=False, show_ad=False)
_ocr = ddddocr.DdddOcr(det=False, ocr=True, show_ad=False)
log.info('模型加载完成')

# ── 字体 ──────────────────────────────────────────────────────────
# 跨平台中文字体关键字白名单（小写匹配文件名）
# macOS 原生中文、苹方、思源、Noto、微软雅黑/宋体/黑体/楷体/仿宋/等线
_CHINESE_FONT_PATTERNS = [
    # macOS
    'PingFang', 'STHeiti', 'Songti', 'Hiragino Sans GB',
    'Kaiti', 'Baoli', 'Hanzipen', 'Lantinghei', 'Libian',
    'Weibei', 'Wawati', 'Xingkai', 'Yuanti', 'Yuppy',
    'Heiti', 'Fangsong', 'Arial Unicode',
    # Windows
    'msyh', 'msyhbd', 'simsun', 'simhei', 'simkai', 'simfang',
    'simyou', 'simli', 'deng', 'dengxian', 'fzhei', 'fzshu',
    'fzjk', 'fzxbs', 'fzxh', 'fzfs', 'fzshuxs',
    # Linux 思源/Noto
    'noto', 'sourcehan', 'wqy', 'arphic', 'cjk',
    # 等线（DengXian 同族）
    'dengxian',
]

_all_font_paths = []


def _list_font_files(roots):
    """在 roots 列表下递归找 .ttf / .ttc / .otf"""
    import glob
    out = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for ext in ('ttf', 'ttc', 'otf'):
            # 加 NUL 规范化以兼容 Windows 长路径/奇怪字符
            pattern_t = os.path.join(root, '**', f'*.{ext}')
            try:
                out.extend(glob.glob(pattern_t, recursive=True))
            except Exception:
                pass
    # 去重并按文件名排序,稳定可复现
    return sorted(set(out))


def _filter_chinese(paths):
    """按关键字白名单过滤, 排除明显非中文（如 Arial、Times）"""
    keep = []
    for p in paths:
        base = os.path.basename(p).lower()
        if any(pat.lower() in base for pat in _CHINESE_FONT_PATTERNS):
            keep.append(p)
    return keep


def _scan_fonts():
    """启动时扫描系统内符合白名单的中文字体, 并验证确实能渲染中文(而非 fallback)"""
    sysname = platform.system()

    if sysname == 'Windows':
        # 1) Windows 系统字体目录
        roots = [r'C:\Windows\Fonts']
        # 2) 用户自定义(可放项目级字体)
        custom = os.environ.get('CAPTCHA_FONT_DIR', '').strip()
        if custom:
            roots.append(custom)
        all_paths = _list_font_files(roots)
    elif sysname == 'Darwin':
        all_paths = _list_font_files(['/System/Library/Fonts', '/Library/Fonts'])
    else:
        # Linux / WSL / 其他
        roots = [
            '/usr/share/fonts',
            '/usr/local/share/fonts',
            os.path.expanduser('~/.fonts'),
            os.path.expanduser('~/.local/share/fonts'),
        ]
        custom = os.environ.get('CAPTCHA_FONT_DIR', '').strip()
        if custom:
            roots.append(custom)
        all_paths = _list_font_files(roots)

    candidates = _filter_chinese(all_paths)
    log.info(f'[{sysname}] 找到 {len(candidates)} 个候选中文字体文件')

    # 2. 对每个文件尝试所有 index, 用"拉丁字 vs 中文字"宽度对比排除 fallback
    seen = set()
    for path in candidates:
        if path in seen:
            continue
        for idx in range(8):
            try:
                font = ImageFont.truetype(path, 40, index=idx)
            except Exception:
                break
            # 画一个中文字和一个拉丁字, 如果中文字宽度明显大于拉丁字,
            # 说明该字体具备原生中文字形(fallback 到 .notdef 时两者宽度接近)。
            # 用 font.getbbox 拿逻辑宽度, 不要依赖像素 getbbox(白底非零会返回整画布)
            try:
                cn_bb = font.getbbox('测')
                en_bb = font.getbbox('A')
                cn_w = cn_bb[2] - cn_bb[0]
                en_w = en_bb[2] - en_bb[0]
            except Exception:
                continue
            if cn_w >= 25 and cn_w >= en_w * 1.3:
                _all_font_paths.append((path, idx))
                seen.add(path)
                break

    log.info(f'扫描到 {len(_all_font_paths)} 个中文字体(已验证可渲染中文)')


_scan_fonts()

FEAT_SIZE = 32
_font_obj_cache = {}
_variant_cache = {}

_HALF = FEAT_SIZE // 2


def _hog_compute(img, win_size, cell_size, block_size, block_stride, nbins=9):
    """手动实现 HOG 特征提取，替代 OpenCV 5.x 已移除的 cv2.HOGDescriptor"""
    win_h, win_w = win_size
    cell_h, cell_w = cell_size
    block_h, block_w = block_size
    stride_h, stride_w = block_stride

    n_cells_x = win_w // cell_w
    n_cells_y = win_h // cell_h
    cbx = block_w // cell_w
    cby = block_h // cell_h
    n_blocks_x = (n_cells_x - cbx) // (stride_w // cell_w) + 1
    n_blocks_y = (n_cells_y - cby) // (stride_h // cell_h) + 1

    gx = cv2.Sobel(img, cv2.CV_32F, 1, 0, ksize=1)
    gy = cv2.Sobel(img, cv2.CV_32F, 0, 1, ksize=1)
    mag = np.sqrt(gx ** 2 + gy ** 2)
    ang = np.arctan2(gy, gx) * 180 / np.pi
    ang[ang < 0] += 180

    cell_hist = np.zeros((n_cells_y, n_cells_x, nbins), dtype=np.float32)
    bin_w = 180.0 / nbins
    for cy in range(n_cells_y):
        for cx in range(n_cells_x):
            yy, xx = cy * cell_h, cx * cell_w
            cm = mag[yy:yy + cell_h, xx:xx + cell_w]
            ca = ang[yy:yy + cell_h, xx:xx + cell_w]
            for by in range(cell_h):
                for bx in range(cell_w):
                    a = ca[by, bx]
                    m = cm[by, bx]
                    bi = int(a / bin_w)
                    bf = (a - bi * bin_w) / bin_w
                    if bi >= nbins - 1:
                        cell_hist[cy, cx, nbins - 1] += m
                    else:
                        cell_hist[cy, cx, bi] += m * (1 - bf)
                        cell_hist[cy, cx, bi + 1] += m * bf

    eps = 1e-5
    feats = []
    for by in range(n_blocks_y):
        for bx in range(n_blocks_x):
            cy0 = by * (stride_h // cell_h)
            cx0 = bx * (stride_w // cell_w)
            bh = cell_hist[cy0:cy0 + cby, cx0:cx0 + cbx].flatten()
            n = np.sqrt(np.sum(bh ** 2) + eps)
            bh = bh / n
            bh = np.clip(bh, 0, 0.2)
            n = np.sqrt(np.sum(bh ** 2) + eps)
            bh = bh / n
            feats.extend(bh)
    return np.array(feats, dtype=np.float32)


def _to_hog(arr_norm):
    """全局 HOG + 四象限 HOG 拼接 → 324+4×144=900 维"""
    img2d = (arr_norm.reshape(FEAT_SIZE, FEAT_SIZE) * 255).astype(np.uint8)
    feat = _hog_compute(img2d, (32, 32), (8, 8), (16, 16), (8, 8), nbins=9)
    for y1, y2, x1, x2 in [
        (0, _HALF, 0, _HALF),
        (0, _HALF, _HALF, FEAT_SIZE),
        (_HALF, FEAT_SIZE, 0, _HALF),
        (_HALF, FEAT_SIZE, _HALF, FEAT_SIZE),
    ]:
        quad = _hog_compute(img2d[y1:y2, x1:x2], (16, 16), (4, 4), (8, 8), (8, 8), nbins=9)
        feat = np.concatenate([feat, quad])
    return feat


def _get_font(path, idx, size):
    key = (path, idx, size)
    if key not in _font_obj_cache:
        try:
            _font_obj_cache[key] = ImageFont.truetype(path, size, index=idx)
        except Exception:
            return None
    return _font_obj_cache[key]


def _render_variants(char):
    """
    渲染单个汉字的所有变体（多字体 × 多尺寸 × 多角度）。
    结果全局缓存，相同字只渲染一次。
    """
    if char in _variant_cache:
        return _variant_cache[char]

    variants = []
    for size in [30, 36, 42]:
        for path, idx in _all_font_paths:
            font = _get_font(path, idx, size)
            if not font:
                continue
            for angle in [-25, -15, 0, 15, 25]:
                canvas = size + 30
                # 黑底白字渲染,getbbox 能正确返回字形边框
                img = Image.new('L', (canvas, canvas), 0)
                draw = ImageDraw.Draw(img)
                draw.text((15, 10), char, fill=255, font=font)
                bbox = img.getbbox()
                if bbox:
                    img = img.crop(bbox)
                if angle != 0:
                    img = img.rotate(angle, fillcolor=0, expand=False)
                img = img.resize((FEAT_SIZE, FEAT_SIZE), Image.LANCZOS)
                arr = np.array(img, dtype=np.float32) / 255.0  # 文字=1.0,背景=0.0
                variants.append(_to_hog(arr.flatten()))

    _variant_cache[char] = variants
    log.info(f'渲染 "{char}": {len(variants)} 个变体')
    return variants


# ── 预处理 ────────────────────────────────────────────────────────

def _crop_image(img: Image.Image, box: list) -> bytes:
    x1, y1, x2, y2 = box
    pad = 3
    x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
    x2, y2 = min(img.width, x2 + pad), min(img.height, y2 + pad)
    cropped = img.crop((x1, y1, x2, y2))
    buf = io.BytesIO()
    cropped.save(buf, format='PNG')
    return buf.getvalue()


def _arr_to_bytes(arr):
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(buf, format='PNG')
    return buf.getvalue()


def _extract_feat(pil_img):
    """从检测区域提取 HOG 特征向量(笔画方向直方图)"""
    gray = np.array(pil_img.convert('L'))
    # CLAHE 增强对比度
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    enhanced = clahe.apply(gray)
    # 自适应二值化
    binary = cv2.adaptiveThreshold(
        enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )
    # 检测背景明暗:若多数像素是黑(说明二值化后前景=白底),不动;否则反色,确保前景=白
    if (binary == 0).sum() < (binary == 255).sum():
        binary = 255 - binary
    resized = cv2.resize(binary, (FEAT_SIZE, FEAT_SIZE), interpolation=cv2.INTER_LANCZOS4)
    arr = resized.astype(np.float32) / 255.0  # 前景=1.0,背景=0.0
    return _to_hog(arr.flatten())


def _ocr_ensemble(crop_bytes):
    """
    同一区域用 5 种预处理分别 OCR，返回 (最佳字符, 置信度, 所有结果集合)。
    """
    img = Image.open(io.BytesIO(crop_bytes))
    gray = np.array(img.convert('L'))

    results = []
    # 1. 原图
    results.append(_ocr.classification(crop_bytes))
    # 2. Otsu 二值化
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    results.append(_ocr.classification(_arr_to_bytes(binary)))
    # 3. CLAHE 增强
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    results.append(_ocr.classification(_arr_to_bytes(clahe.apply(gray))))
    # 4. 反色
    results.append(_ocr.classification(_arr_to_bytes(255 - gray)))
    # 5. 高斯模糊 + Otsu
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary2 = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    results.append(_ocr.classification(_arr_to_bytes(binary2)))

    counter = Counter(results)
    char, count = counter.most_common(1)[0]
    confidence = count / len(results)
    return char, confidence, set(results)


# ── 相似度 ────────────────────────────────────────────────────────

def _cosine_sim(a, b):
    a = a - a.mean()
    b = b - b.mean()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-7 or nb < 1e-7:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _best_variant_sim(variants, feat):
    """在所有渲染变体中找最高相似度"""
    best = -1.0
    for v in variants:
        s = _cosine_sim(v, feat)
        if s > best:
            best = s
    return best


def _dist(a, b):
    return ((a['x'] - b['x']) ** 2 + (a['y'] - b['y']) ** 2) ** 0.5


# ── 核心识别 ──────────────────────────────────────────────────────

def solve_click_captcha(img_bytes: bytes, prompt: str) -> list[dict]:
    # ── 1. 检测 ──
    boxes = _det.detection(img_bytes)
    if not boxes:
        raise ValueError('未检测到任何目标')

    img = Image.open(io.BytesIO(img_bytes))
    min_dist = min(img.width, img.height) * 0.10

    # ── 2. 裁剪 + OCR 集成 + 特征提取 ──
    detected = []
    for box in boxes:
        crop_bytes = _crop_image(img, box)
        char, confidence, all_results = _ocr_ensemble(crop_bytes)
        cx = (box[0] + box[2]) / 2
        cy = (box[1] + box[3]) / 2
        crop_img = Image.open(io.BytesIO(crop_bytes))
        feat = _extract_feat(crop_img)
        detected.append({
            'char': char,
            'confidence': confidence,
            'all_ocr': all_results,
            'x': cx, 'y': cy,
            'feat': feat,
        })

    ocr_summary = [f'{d["char"]}({d["confidence"]:.0%})' for d in detected]
    log.info(f'检测到 {len(detected)} 个目标: {ocr_summary}')
    log.info(f'提示字符: {list(prompt)}, 最小距离: {min_dist:.0f}px')

    # ── 3. 渲染提示字变体 ──
    prompt_vars = {}
    for ch in set(prompt):
        prompt_vars[ch] = _render_variants(ch)

    # ── 4. 综合评分矩阵 ──
    n = len(prompt)
    m = len(detected)
    score = [[0.0] * m for _ in range(n)]

    for pi in range(n):
        variants = prompt_vars[prompt[pi]]
        for di in range(m):
            # (a) 图像相似度 (范围约 -1 ~ 1) —— 主导项
            img_sim = _best_variant_sim(variants, detected[di]['feat'])

            # (b) OCR 集成加分 —— 仅作辅助信号,不能压过图像相似度
            # img_sim 大致 0.2~0.7 区分不同字,OCR bonus 上限 0.3 仅微调
            ocr_bonus = 0.0
            if detected[di]['char'] == prompt[pi]:
                ocr_bonus = 0.3 * detected[di]['confidence']
            elif prompt[pi] in detected[di]['all_ocr']:
                ocr_bonus = 0.1

            score[pi][di] = img_sim + ocr_bonus

    # 打印评分矩阵
    for pi in range(n):
        row = ', '.join(f'{score[pi][di]:.2f}' for di in range(m))
        log.info(f'评分[{prompt[pi]}]: [{row}]')

    # ── 5. 全排列搜索（找总分最高的合法分配） ──
    best_total = -float('inf')
    best_perm = None

    for perm in permutations(range(m), n):
        # 距离约束
        ok = True
        for i in range(n):
            for j in range(i + 1, n):
                if _dist(detected[perm[i]], detected[perm[j]]) < min_dist:
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            continue

        total = sum(score[i][perm[i]] for i in range(n))
        if total > best_total:
            best_total = total
            best_perm = perm

    # 无合法分配时放宽约束
    if best_perm is None:
        log.warning('无可行分配，放宽距离约束')
        for perm in permutations(range(m), n):
            total = sum(score[i][perm[i]] for i in range(n))
            if total > best_total:
                best_total = total
                best_perm = perm

    # ── 6. 组装结果 ──
    result = []
    for i in range(n):
        di = best_perm[i]
        d = detected[di]
        result.append({'x': round(d['x'], 1), 'y': round(d['y'], 1)})
        log.info(
            f'  "{prompt[i]}" → 检测[{di}] '
            f'(OCR="{d["char"]}" {d["confidence"]:.0%}, '
            f'score={score[i][di]:.3f})'
        )

    return result


# ── HTTP ──────────────────────────────────────────────────────────

@app.route('/click', methods=['POST'])
def click():
    t0 = time.time()
    try:
        data = request.get_json(force=True)
        image_b64 = data.get('image', '')
        prompt = data.get('remark', '')

        if not image_b64 or not prompt:
            return jsonify({'success': False, 'message': '缺少参数'}), 400

        img_bytes = base64.b64decode(image_b64)
        points = solve_click_captcha(img_bytes, prompt)
        result_str = '|'.join(f'{p["x"]},{p["y"]}' for p in points)

        elapsed = (time.time() - t0) * 1000
        log.info(f'完成: prompt="{prompt}" result="{result_str}" 耗时={elapsed:.0f}ms')

        return jsonify({
            'success': True,
            'data': {'result': result_str, 'id': ''}
        })
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        log.error(f'失败 ({elapsed:.0f}ms): {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'engine': 'ddddocr', 'fonts': len(_all_font_paths)})


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='ddddocr 点选验证码识别服务')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9898)
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    log.info(f'启动: http://{args.host}:{args.port} ({len(_all_font_paths)} 个中文字体)')
    app.run(host=args.host, port=args.port, debug=args.debug)
