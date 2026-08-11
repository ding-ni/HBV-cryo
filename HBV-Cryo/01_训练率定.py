# -*- coding: utf-8 -*-
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "HBV-Studio"))

from 公共函数 import example_config_path, temporary_argv
from profile_runner import main as studio_profile_main
from profile_runner import PARAM_BOUNDS_PROFILE_GENERIC, PARAM_BOUNDS_PROFILE_QTP


def main():
    parser = argparse.ArgumentParser(description="率定 HBV-Cryo 参数。统一转到 HBV-Studio/profile_runner.py。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument("--率定模式", "--calibration-mode", dest="率定模式", choices=["daily", "hourly"], default=None)
    parser.add_argument("--目标函数", "--objective-mode", dest="目标函数", default=None)
    parser.add_argument("--降水源", "--prec-source", dest="降水源", choices=["era5", "mswep", "cmfd", "custom_tif"], default=None)
    parser.add_argument("--prec-dir", type=str, default="")
    parser.add_argument("--冰川模式", "--glacier-mode", dest="冰川模式", choices=["inline", "off"], default="inline")
    parser.add_argument("--method", choices=["de", "mc_screen_de", "mc_only"], default="mc_screen_de")
    parser.add_argument("--mc-samples", type=int, default=600)
    parser.add_argument("--refine-maxiter", dest="refine_maxiter", type=int, default=-1)
    parser.add_argument("--init-params-file", type=str, default=None)
    parser.add_argument("--init-bound-shrink", type=float, default=0.0)
    parser.add_argument("--param-bounds-profile", "--参数边界档案", dest="param_bounds_profile", choices=[PARAM_BOUNDS_PROFILE_QTP, PARAM_BOUNDS_PROFILE_GENERIC], default=None)
    parser.add_argument("--calibration-workflow", default="")
    parser.add_argument("--maxiter", type=int, default=40)
    parser.add_argument("--popsize", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--debug-days", type=int, default=0)
    parser.add_argument("--quick-test", action="store_true")
    parser.add_argument("--quick-days", type=int, default=30)
    args = parser.parse_args()

    argv = [
        "01_训练率定.py",
        "--config",
        str(args.配置),
        "--glacier-mode",
        args.冰川模式,
        "--method",
        args.method,
        "--mc-samples",
        str(args.mc_samples),
        "--maxiter",
        str(args.maxiter),
        "--popsize",
        str(args.popsize),
        "--seed",
        str(args.seed),
        "--workers",
        str(args.workers),
    ]
    if args.率定模式:
        argv.extend(["--calibration-mode", args.率定模式])
    if args.目标函数:
        argv.extend(["--objective-mode", args.目标函数])
    if args.降水源:
        argv.extend(["--prec-source", args.降水源])
    if args.prec_dir:
        argv.extend(["--prec-dir", str(args.prec_dir)])
    if args.calibration_workflow:
        argv.extend(["--calibration-workflow", str(args.calibration_workflow)])
    if args.init_params_file:
        argv.extend(["--init-params-file", str(args.init_params_file), "--init-bound-shrink", str(args.init_bound_shrink)])
    if args.param_bounds_profile:
        argv.extend(["--param-bounds-profile", str(args.param_bounds_profile)])
    if int(getattr(args, "refine_maxiter", -1)) != -1:
        argv.extend(["--refine-maxiter", str(args.refine_maxiter)])
    if args.debug_days > 0:
        argv.extend(["--debug-days", str(args.debug_days)])
    if args.quick_test:
        argv.extend(["--quick-test", "--quick-days", str(args.quick_days)])

    with temporary_argv(argv):
        studio_profile_main()


if __name__ == "__main__":
    main()
