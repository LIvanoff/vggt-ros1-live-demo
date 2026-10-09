# Jetson Thor: экспериментальный запуск

На реальном Thor этот репозиторий ещё не запускался. Подготовлены Linux-команды,
ROS-образ ARM64 и worker CUDA с BF16/FP16/FP32. Windows INT8 использует CPU:
это отдельный режим, не TensorRT INT8 и не CUDA INT8.

## 1. Проверить NVIDIA-окружение

Проверьте версию JetPack/драйвера на вашем устройстве и установку NVIDIA Container
Toolkit по [официальной инструкции Thor](https://docs.nvidia.com/jetson/agx-thor-devkit/user-guide/latest/setup_docker.html).
В ней приведён `nvcr.io/nvidia/pytorch:25.08-py3`; он выбран базой по умолчанию.
Если вашей версии JetPack нужен другой образ, задайте `TORCH_IMAGE` перед сборкой.
Не устанавливайте поверх него CPU PyTorch из Windows setup_worker.ps1.

```bash
git clone https://github.com/LIvanoff/vggt-ros1-live-demo.git
cd vggt-ros1-live-demo
docker run --rm --gpus all nvcr.io/nvidia/pytorch:25.08-py3 \
  python3 -c 'import torch; print(torch.__version__, torch.version.cuda); assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0)); x=torch.randn(256,256,device="cuda"); print((x@x).sum().item())'
```

Нужны `CUDA available` по проверке assert и успешное вычисление на GPU. Если оно
не выполняется, сначала исправьте драйвер/образ/runtime; до запуска VGGT дело ещё
не дошло. Compose должен поддерживать [`gpus: all`](https://docs.docker.com/reference/compose-file/services/#gpus) (Docker Compose 2.30+).

## 2. Собрать контейнеры и загрузить модель

```bash
docker compose --profile jetson build ros worker
mkdir -p data models external outputs bridge
# Контейнеры скачивания пишут файлы от текущего пользователя.
docker compose --profile jetson run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  worker python3 tools/download_source.py
docker compose --profile jetson run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  worker python3 tools/download_model.py
```

Вместо повторной загрузки можно перенести с ноутбука `models/` и `external/vggt/`.
Checkpoint должен называться `models/model.safetensors`; размер 5 026 367 224 байта,
SHA-256 `f164acf60724910d8fe1578bb499d800850c7bb0948db7555c413f9fbe60467e`.
Контейнер NVIDIA и зависимости тоже занимают место; 5 ГБ — только веса.

Скопируйте bag с ноутбука в `data/nuplan_front_2hz.bag`.
Исходный локальный файл находится в папке live_vggt_ros1/data ноутбука; в GitHub его нет.
Не переносите Windows `.venv`, а также catkin `build/` и `devel/` между платформами.

```bash
bash run.sh build
```

`run.sh` передаёт UID/GID текущего пользователя в ROS-контейнер. Worker запускается
с теми же UID/GID: оба процесса могут записывать файлы задания в `bridge/`.
Для запуска ROS через Compose напрямую экспортируйте `LOCAL_UID=$(id -u)` и
`LOCAL_GID=$(id -g)`. Команды `run.sh` уже делают это автоматически.

## 3. Запустить сквозную демонстрацию

Все терминалы — в корне репозитория:

```bash
# Терминал 1
bash run.sh roscore
# Терминал 2: дождаться "VGGT loaded on cuda ... waiting for a ROS job"
bash run.sh worker-jetson
# Терминал 3
bash run.sh node 2
# Терминал 4: нажать пробел, чтобы начать проигрывание
bash run.sh bag
```

Параметры worker: `--device cuda --precision bf16 --width 280 --once --no-viewer`.
BF16 применяется через autocast; параметры модели загружаются в FP32.
До загрузки проверяется наличие минимум 16 GiB доступной системной RAM — это
консервативный стартовый порог, не измеренный пик Thor и не гарантия отсутствия OOM.
На Jetson память разделяют CPU и GPU. Первую попытку делайте только на двух кадрах.

Пример явного выбора FP16:

```bash
docker compose --profile jetson run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp worker \
  python3 worker/watch.py --device cuda --precision fp16 --width 280 \
  --min-free-ram-gib 16 --no-viewer --once
```

Ожидаемые результаты: `bridge/<job>/report.json`, `result.npz`, запись
`outputs/scene_<job>.rrd` и топик `/vggt/points`. В отчёте должны быть `device: cuda`,
выбранная precision и фактическое время. Не используйте результаты CPU как оценку
скорости или качества Thor.

```bash
docker compose exec ros bash -lc 'source /opt/ros/noetic/setup.bash && rostopic echo -n 1 /vggt/points/header'
docker compose exec ros bash -lc 'source /opt/ros/noetic/setup.bash && rostopic hz /vggt/points'
```

Облако публикуется один раз с latch: у `rostopic hz` не будет устойчивой частоты.
Для повторения остановите ROS-ноду, заново запустите worker, ноду и bag.

## 4. Посмотреть результат без X11

Worker на Thor сохраняет RRD и не запускает GUI. Скопируйте запись на ноутбук:

```bash
# На ноутбуке, подставив пользователя, адрес Thor, путь и имя файла:
scp USER@THOR:/absolute/path/vggt-ros1-live-demo/outputs/scene_JOB_ID.rrd .
```

В подготовленном Windows-окружении:

```powershell
.\.venv\Scripts\python.exe -m rerun .\scene_JOB_ID.rrd
```

Для отдельного Viewer достаточно `pip install rerun-sdk==0.23.4` в отдельном
окружении Python и `python -m rerun scene_JOB_ID.rrd`.
Передача X11, DISPLAY и запуск Viewer внутри NVIDIA-контейнера не нужны.

После работы:

```bash
bash run.sh stop
```

## Что проверять при первом запуске

- CUDA-тест проходит внутри того же образа, где запускается worker.
- В `report.json` нет ошибки; `device` и `precision` соответствуют команде.
- В Rerun видны изображение, камеры и облако; отдельно оцените искажения геометрии.
- Сравнивайте BF16/FP32 на одинаковых кадрах, если нужна оценка влияния precision.
- `frame_id=vggt_world`, масштаб произвольный. Это не метрическая карта для автомобиля.

Параметры `tests/rehearse_live.py --device cuda --precision bf16` пригодны, если
Python с CUDA установлен на хосте Thor и оттуда доступен Docker CLI. В контейнере
worker этот тест не запускается автоматически: Docker socket туда не проброшен.
