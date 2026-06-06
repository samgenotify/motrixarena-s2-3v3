# README_步态.md — 步态模型交付说明

## 模型信息

- **文件名**: `k1_amp_20000.onnx`
- **方案类型**: 方案 A — K1 AMP / 全关节步态（与当前 MotrixSim 对齐）
- **训练框架**: legged_gym + AMP (Adversarial Motion Prior)
- **训练步数**: 20000 iterations
- **来源**: 官方默认模型（赛事方提供，未做二次训练）

## 输入/输出维度

| 项目 | 名称 | 形状 | 数据类型 |
|------|------|------|----------|
| 输入 | `nn_input` | `[1, 375]` | float32 |
| 输出 | `nn_output` | `[1, 22]` | float32 |

- 输入 375 维：本体观测 + 关节位置/速度 + 上一步动作 + IMU + 高度扫描等
- 输出 22 维：K1 机器人 22 个关节的目标位置（PD 控制目标）

## 自检记录

```bash
# onnxruntime 本地推理测试通过
python -c "
import onnxruntime as ort
sess = ort.InferenceSession('gait/k1_amp_20000.onnx')
print('Inputs:', [(i.name, i.shape, i.type) for i in sess.get_inputs()])
print('Outputs:', [(o.name, o.shape, o.type) for o in sess.get_outputs()])
"
# Outputs: Inputs: [('nn_input', [1, 375], 'tensor(float)')]
#          Outputs: [('nn_output', [1, 22], 'tensor(float)')]
```

- ✅ 单输入单输出
- ✅ 文件路径无中文无空格
- ✅ 输入输出维度与官方约定一致

## 归一化说明

观测向量在训练时由 `legged_gym` 框架自动归一化（RunningMeanStd），部署时由 `motrixsim` 的 `policy_runner.py` 自动调用 ONNX Runtime，无需手动归一化。

## 文件清单

```
gait/
└── k1_amp_20000.onnx    # 1.5MB, SHA256 待补
```

## 备注

- 本模型为赛事官方默认模型，未做二次训练
- 如赛事方允许自定义步态，可替换为队伍自训练模型
- 替换时需保证输入维度仍为 375、输出 22，且 `robot_type=k1`
