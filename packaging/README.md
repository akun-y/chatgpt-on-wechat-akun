# Packaging Guide

## 环境
- Conda 环境路径: `D:\conda_envs\wework`
- 默认解释器: `D:\conda_envs\wework\python.exe`

## 一键打包
在仓库根目录执行:

```powershell
.\packaging\build_release.ps1
```

## 输出目录
- `release/cow-wework-akun/cow-wework-akun.exe`
- `release/cow-wework-akun/config.json`
- `release/cow-wework-akun/config-template.json`
- `release/cow-wework-akun/config-template.wework.json`
- `release/cow-wework-akun/ecosystem.config.js`
- `release/cow-wework-akun/README-PM2.md`
- `release/cow-wework-akun/logs`
- `release/cow-wework-akun/tmp`

## 指定 Python（可选）

```powershell
$env:WEWORK_PYTHON="D:\conda_envs\wework\python.exe"
.\packaging\build_release.ps1
```
