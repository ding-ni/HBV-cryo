# -*- coding: utf-8 -*-
"""
阶段1：GIS 水文分析
生成流向栅格和流量累积栅格

支持两种方式：
1. WhiteboxTools (推荐)
2. ArcPy (备选)

输入：
- 数据/地理数据/dem_1km.tif  DEM栅格

输出：
- 数据/地理数据/dem_filled.tif      填洼后的DEM
- 数据/地理数据/flow_direction.tif  D8流向栅格
- 数据/地理数据/flow_accumulation.tif 流量累积栅格
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

# ============================================================
# 路径配置
# ============================================================
def _prefer_existing_path(*paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return paths[0]


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "运行目录", "默认流域"))
DATA_ROOT = _prefer_existing_path(os.path.join(PROJECT_ROOT, "数据"), os.path.join(PROJECT_ROOT, "data"))
GIS_DIR = _prefer_existing_path(os.path.join(DATA_ROOT, "地理数据"), os.path.join(DATA_ROOT, "gis"))

# 输入文件
DEM_INPUT = os.path.join(GIS_DIR, "dem_1km.tif")

# 输出文件
DEM_FILLED = os.path.join(GIS_DIR, "dem_filled.tif")
FLOW_DIR = os.path.join(GIS_DIR, "flow_direction.tif")
FLOW_ACC = os.path.join(GIS_DIR, "flow_accumulation.tif")


# ============================================================
# 方法1：使用 WhiteboxTools
# ============================================================
def _whitebox_exe_name():
    return "whitebox_tools.exe" if os.name == "nt" else "whitebox_tools"


def _iter_whitebox_candidate_dirs():
    seen = set()

    def add(path_value):
        if not path_value:
            return
        try:
            candidate = Path(path_value).expanduser().resolve()
        except OSError:
            candidate = Path(path_value).expanduser()
        key = str(candidate).lower()
        if key in seen:
            return
        seen.add(key)
        yield candidate

    env_path = os.environ.get("WBT_PATH")
    if env_path:
        yield from add(env_path)

    try:
        import whitebox.whitebox_tools as whitebox_tools_module

        package_dir = Path(whitebox_tools_module.__file__).resolve().parent
        yield from add(package_dir)
        yield from add(package_dir / "WBT")
    except Exception:
        pass

    exe_path = shutil.which(_whitebox_exe_name()) or shutil.which("whitebox_tools")
    if exe_path:
        yield from add(Path(exe_path).parent)

    roots = set()
    for raw_root in {
        Path(sys.executable).resolve().parent,
        Path(sys.prefix),
        Path(getattr(sys, "base_prefix", sys.prefix)),
    }:
        roots.add(raw_root)
        roots.add(raw_root.parent)
        roots.add(raw_root.parent.parent)

    for root in roots:
        for rel in (
            Path("Lib") / "site-packages" / "whitebox",
            Path("lib") / "site-packages" / "whitebox",
        ):
            yield from add(root / rel)


def _find_whitebox_dir():
    exe_name = _whitebox_exe_name()
    for directory in _iter_whitebox_candidate_dirs():
        if (directory / exe_name).exists():
            return directory
    return None


def _create_whitebox_tools():
    import whitebox.whitebox_tools as whitebox_tools_module

    whitebox_dir = _find_whitebox_dir()
    if whitebox_dir is None:
        raise FileNotFoundError(
            "未找到 WhiteboxTools 可执行文件。请安装带二进制的 whitebox，"
            "或手工设置环境变量 WBT_PATH 指向包含 whitebox_tools.exe 的目录。"
        )

    original_download = whitebox_tools_module.download_wbt
    whitebox_tools_module.download_wbt = lambda *args, **kwargs: None
    try:
        wbt = whitebox_tools_module.WhiteboxTools()
    finally:
        whitebox_tools_module.download_wbt = original_download

    wbt.set_whitebox_dir(str(whitebox_dir))
    return wbt, whitebox_dir


def _whitebox_scratch_root():
    env_root = os.environ.get("HBV_WBT_SCRATCH_ROOT", "").strip()
    candidates = []
    if env_root:
        candidates.append(Path(env_root).expanduser())
    for anchor in (
        Path(PROJECT_ROOT).resolve().anchor,
        Path(sys.executable).resolve().anchor,
        Path.cwd().resolve().anchor,
    ):
        if anchor:
            candidates.append(Path(anchor) / "HBVStudio_Scratch")
    fallback = Path(tempfile.gettempdir()) / "HBVStudio_Scratch"
    candidates.append(fallback)
    seen = set()
    for candidate in candidates:
        text = str(candidate)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    raise OSError("无法创建 WhiteboxTools 临时工作目录。")


def run_whitebox():
    """使用 WhiteboxTools 进行水文分析"""
    wbt, whitebox_dir = _create_whitebox_tools()
    # Whitebox 原生命令行在中文 Windows 下经常输出本地编码文本，
    # 会把任务日志刷得很多且容易出现乱码。这里关闭其详细输出，
    # 仅保留我们自己控制的中文进度提示。
    wbt.verbose = False

    print("=" * 60)
    print("使用 WhiteboxTools 进行水文分析")
    print("=" * 60)
    print(f"WhiteboxTools 目录: {whitebox_dir}")

    # 检查输入文件
    if not os.path.exists(DEM_INPUT):
        print(f"[ERROR] DEM文件不存在: {DEM_INPUT}")
        print("   请先将 DEM 放入 数据/地理数据/ 目录")
        return False

    # WhiteboxTools on Windows is not reliable with non-ASCII working paths.
    # Run in a temporary ASCII-only workspace, then copy outputs back.
    scratch_root = _whitebox_scratch_root()
    scratch = Path(tempfile.mkdtemp(prefix="hbv_wbt_", dir=str(scratch_root)))
    try:
        scratch_dem = scratch / Path(DEM_INPUT).name
        scratch_filled = scratch / Path(DEM_FILLED).name
        scratch_flow_dir = scratch / Path(FLOW_DIR).name
        scratch_flow_acc = scratch / Path(FLOW_ACC).name

        shutil.copy2(DEM_INPUT, scratch_dem)
        wbt.work_dir = str(scratch)
        print(f"临时工作目录: {scratch}")

        # 步骤1：填充洼地
        print("\n[1/3] 填充洼地...")
        wbt.fill_depressions(
            dem=scratch_dem.name,
            output=scratch_filled.name
        )
        if not scratch_filled.exists():
            raise RuntimeError("WhiteboxTools 未生成 dem_filled.tif。")
        shutil.copy2(scratch_filled, DEM_FILLED)
        print(f"   输出: {DEM_FILLED}")

        # 步骤2：生成 D8 流向
        print("\n[2/3] 生成 D8 流向...")
        wbt.d8_pointer(
            dem=scratch_filled.name,
            output=scratch_flow_dir.name
        )
        if not scratch_flow_dir.exists():
            raise RuntimeError("WhiteboxTools 未生成 flow_direction.tif。")
        shutil.copy2(scratch_flow_dir, FLOW_DIR)
        print(f"   输出: {FLOW_DIR}")

        # 步骤3：生成流量累积
        print("\n[3/3] 生成流量累积...")
        wbt.d8_flow_accumulation(
            i=scratch_filled.name,
            output=scratch_flow_acc.name,
            out_type="cells"  # 输出单元格数量
        )
        if not scratch_flow_acc.exists():
            raise RuntimeError("WhiteboxTools 未生成 flow_accumulation.tif。")
        shutil.copy2(scratch_flow_acc, FLOW_ACC)
        print(f"   输出: {FLOW_ACC}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    print("\n[OK] WhiteboxTools 水文分析完成！")
    return True


# ============================================================
# 方法2：使用 ArcPy
# ============================================================
def run_arcpy():
    """使用 ArcPy 进行水文分析"""
    import arcpy
    from arcpy.sa import Fill, FlowDirection, FlowAccumulation

    # 启用空间分析扩展
    arcpy.CheckOutExtension("Spatial")
    arcpy.env.overwriteOutput = True
    arcpy.env.workspace = GIS_DIR

    print("=" * 60)
    print("使用 ArcPy 进行水文分析")
    print("=" * 60)

    # 检查输入文件
    if not os.path.exists(DEM_INPUT):
        print(f"[ERROR] DEM文件不存在: {DEM_INPUT}")
        print("   请先将 DEM 放入 数据/地理数据/ 目录")
        return False

    # 步骤1：填充洼地
    print("\n[1/3] 填充洼地 (Fill)...")
    dem_filled = Fill(DEM_INPUT)
    dem_filled.save(DEM_FILLED)
    print(f"   输出: {DEM_FILLED}")

    # 步骤2：生成流向
    print("\n[2/3] 生成流向 (D8)...")
    flow_dir = FlowDirection(DEM_FILLED, "NORMAL")
    flow_dir.save(FLOW_DIR)
    print(f"   输出: {FLOW_DIR}")

    # 步骤3：生成流量累积
    print("\n[3/3] 生成流量累积...")
    flow_acc = FlowAccumulation(FLOW_DIR)
    flow_acc.save(FLOW_ACC)
    print(f"   输出: {FLOW_ACC}")

    # 归还扩展许可
    arcpy.CheckInExtension("Spatial")

    print("\n[OK] ArcPy 水文分析完成！")
    return True


# ============================================================
# 验证结果
# ============================================================
def verify_results():
    """验证生成的栅格"""
    import rasterio

    print("\n" + "=" * 60)
    print("验证结果")
    print("=" * 60)

    files = [
        ("DEM (填洼后)", DEM_FILLED),
        ("流向栅格", FLOW_DIR),
        ("流量累积", FLOW_ACC),
    ]

    for name, path in files:
        if os.path.exists(path):
            with rasterio.open(path) as src:
                print(f"\n[OK] {name}")
                print(f"   路径: {path}")
                print(f"   尺寸: {src.width} x {src.height}")
                print(f"   CRS: {src.crs}")
                print(f"   分辨率: {src.res}")
        else:
            print(f"\n[ERROR] {name} - 文件不存在")


# ============================================================
# 主函数
# ============================================================
if __name__ == "__main__":
    print("当前流域水文分析")
    print("=" * 60)

    # 检查DEM是否存在
    if not os.path.exists(DEM_INPUT):
        print(f"\n[WARN] DEM文件尚未准备: {DEM_INPUT}")
        print("请将当前流域 DEM 放入 数据/地理数据/ 目录，命名为 dem_1km.tif")
        print("\n脚本将在DEM准备好后运行")
        sys.exit(0)

    # 尝试使用 WhiteboxTools
    try:
        from whitebox import WhiteboxTools
        success = run_whitebox()
    except ImportError:
        print("WhiteboxTools 未安装，尝试使用 ArcPy...")
        try:
            import arcpy
            success = run_arcpy()
        except ImportError:
            print("[ERROR] 需要安装 WhiteboxTools 或 ArcPy")
            print("   pip install whitebox")
            sys.exit(1)

    # 验证结果
    if success:
        verify_results()

