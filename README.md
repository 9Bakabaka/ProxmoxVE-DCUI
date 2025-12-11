# Proxmox VE DCUI (PVE-DCUI)

一个仿 VMware ESXi 风格的 Proxmox VE 直接控制台用户界面 (DCUI)。

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Platform](https://img.shields.io/badge/platform-Proxmox%20VE-orange.svg)
![Python](https://img.shields.io/badge/python-3.x-yellow.svg)

> **简介:** 这是一个运行在物理终端 (TTY) 上的 Python TUI 程序，旨在为 Proxmox VE 提供类似 ESXi 的管理体验，方便在没有 Web 界面时进行基础的主机管理。

---

## 🤖 声明 / Disclaimer

**Co-authored by AI (Gemini) & User**

**本项目代码由 AI (Google Gemini) 与用户共同编写。**
它展示了利用 AI 辅助进行系统级工具开发的实践。在使用前建议审查代码，虽然已在 PVE 环境测试，但请根据实际情况谨慎使用。

---

## ✨ 主要功能 (Features)

* **经典界面**: 复刻 ESXi 的黄/灰/黑经典配色与布局。
* **系统概览**: 显示主机名、IP 地址 (IPv4/IPv6)、CPU 型号、内存使用、PVE 版本及内核版本。
* **屏幕保护**: 无操作 60 秒后自动变暗，防止烧屏。
* **安全登录**: 支持通过系统本地密码 (PAM/Shadow) 或 PVE API Ticket 进行身份验证。
* **管理菜单**:
    * 配置管理网络 (查看 interfaces)
    * 重启网络服务
    * 网络连通性测试 (Ping Google DNS)
    * 查看系统日志 (`journalctl`)
    * 进入命令行 (Shell)
    * 重启 / 关闭主机

## 🛠 依赖要求 (Prerequisites)

此脚本需要 **Python 3** 环境以及 `psutil` 库。必须以 **root** 权限运行。

在 Proxmox VE 上安装依赖：

```bash
apt update
apt install python3-psutil -y
````

## 🚀 安装与使用 (Installation)

1.  **克隆仓库:**

    ```bash
    git clone [https://github.com/your-username/pve-dcui.git](https://github.com/your-username/pve-dcui.git)
    cd pve-dcui
    ```

2.  **手动运行测试:**

    ```bash
    python3 pve_dcui.py
    ```

## ⚙️ 设置开机自启 (替换默认 TTY1)

为了获得最佳体验，建议将此界面设置为开机自启，替换默认的 TTY1 登录提示符。

### 1\. 放置脚本

将脚本移动到一个固定的位置，例如 `/root/`：

```bash
cp pve_dcui.py /root/pve_dcui.py
chmod +x /root/pve_dcui.py
```

### 2\. 创建 Systemd 服务

新建服务文件 `/etc/systemd/system/pve-dcui.service`：

```ini
[Unit]
Description=Proxmox VE DCUI
After=network.target
# 确保与默认的 getty 服务冲突，从而接管 tty1
Conflicts=getty@tty1.service

[Service]
ExecStart=/usr/bin/python3 /root/pve_dcui.py
StandardInput=tty
StandardOutput=tty
TTYPath=/dev/tty1
Type=simple
Restart=always
# 必须以 root 运行以执行管理任务
User=root
# 设置终端环境变量
Environment=TERM=linux

[Install]
WantedBy=multi-user.target
```

### 3\. 启用服务

禁用默认的 TTY1 getty 服务并启用 PVE-DCUI：

```bash
# 停止并禁用默认的 tty1 登录服务
systemctl stop getty@tty1.service
systemctl disable getty@tty1.service

# 启用并启动自定义 DCUI 服务
systemctl enable pve-dcui.service
systemctl start pve-dcui.service
```

现在，当你连接显示器到 PVE 主机时，应该能看到新的控制台界面了。

## 📸 截图

![主界面](screenshots/dcui.png)

## 📄 许可证 (License)

本项目采用 **MIT License** 开源。

## 🤝 贡献 (Contributing)

欢迎提交 Issue 或 Pull Request！
由于代码部分由 AI 生成，可能存在优化空间，欢迎大家一起来完善它。

