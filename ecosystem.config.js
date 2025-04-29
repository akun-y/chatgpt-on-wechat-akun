module.exports = {
    apps: [
      {
        name: 'chatgpt-wework',
        script: 'app.py',
        interpreter: 'M:/conda-envs/ntwork/python.exe',
        cwd: 'M:/dev/COW/wework-ntwork/chatgpt-on-wechat-wework',
        args: '', // 如果 app.py 需要命令行参数，在此添加，例如 '--port 8080'
        env: {
          PYTHONIOENCODING: 'utf-8', // 确保 Python 输出使用 UTF-8 编码，防止中文乱码
          PYTHONPATH: 'M:/dev/COW/wework-ntwork/chatgpt-on-wechat-wework' // 添加项目目录到 PYTHONPATH
        },
        output: './logs/app-out.log', // 标准输出日志
        error: './logs/app-error.log', // 错误日志
        log_date_format: 'YYYY-MM-DD HH:mm:ss',
        autorestart: false, // 进程崩溃时自动重启
        max_restarts: 100, // 最大重启次数
        restart_delay: 21000, // 重启延迟（毫秒）
        watch: true, // 是否监控文件变化，建议生产环境关闭
        max_memory_restart: '1G', // 内存超限时重启（可选）
        cron_restart: '12 01 * * *', // 每天 01时12分重启
        //cron_restart: '*/3 * * * *' // 每3分钟重启
      }
    ]
  };