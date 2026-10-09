# ROS 1 → VGGT-1B → Rerun

Учебный live-кодинг: ROS-нода читает изображения из bag, собирает два соседних кадра,
передаёт их VGGT-1B и публикует цветное облако `sensor_msgs/PointCloud2`.
Rerun показывает точки, камеры и исходные изображения.

**Для Jetson Thor: [инструкция Linux/CUDA](docs/JETSON_THOR.md).**
Этот путь подготовлен, но на Thor ещё не проверен. Проверенный исходный сценарий —
Windows, CPU, динамический INT8. [Результаты и границы проверки](docs/VALIDATION.md).

```text
ROS 1 bag, JPEG, 2 Hz
  → /camera/front/image_raw/compressed
  → vggt_scene: Subscriber, сбор 2 кадров
  → bridge/<job>/request.json + JPEG
  → отдельный Python worker с VGGT-1B
  → result.npz → /vggt/points (PointCloud2)
               ↘ outputs/scene_<job>.rrd → Rerun
```

ROS Noetic работает в контейнере Ubuntu 20.04. Worker использует отдельный Python:
на Windows — `.venv`, на Thor — NVIDIA PyTorch container. Через ROS передаются
изображения и облако; обмен с worker идёт через общую папку. Интернет во время
инференса не нужен после скачивания исходников, весов и Docker-образов.

## Что есть в репозитории

| Файл | Назначение |
| --- | --- |
| `catkin_ws/src/vggt_scene/scripts/scene_node.py` | Нода, которую пишем на занятии |
| `catkin_ws/src/vggt_scene/src/vggt_scene_lib/io.py` | Готовый файловый обмен и сериализация PointCloud2 |
| `worker/inference.py` | VGGT, восстановление точек, CPU/экспериментальный CUDA |
| `worker/watch.py` | Обработка задания, сохранение результата |
| `worker/viewer.py` | Rerun: облако, положения камер, изображения |
| `docker/`, `compose.yaml` | Самостоятельная сборка окружения |
| `tests/rehearse_live.py` | Настоящий инференс с проверкой опубликованного облака |
| `tests/ros_smoke.py` | Только ROS transport; ответ модели заменён тестовыми данными |

Веса, исходные данные, bag, `.venv`, сторонние исходники и записи Rerun не включены.
Скрипты скачивают VGGT из официальных источников с зафиксированными ревизиями.
Bag перенесите самостоятельно: [формат входа и создание bag](data/README.md).

## Быстрый запуск на Windows CPU

Нужны Docker Desktop с Linux containers и Python 3.12. Все команды выполняются
из корня этого репозитория. Один checkpoint занимает 5,03 ГБ; установщик требует
ещё 2 GiB свободного диска. Для остальных зависимостей и Docker нужно отдельное место.

```powershell
git clone https://github.com/LIvanoff/vggt-ros1-live-demo.git
cd vggt-ros1-live-demo
.\setup_worker.ps1
# Скопировать nuplan_front_2hz.bag в data/
.\run.ps1 build
```

Открыть четыре терминала PowerShell в этой папке:

```powershell
# Терминал 1
.\run.ps1 roscore
# Терминал 2: дождаться сообщения "VGGT loaded ... waiting for a ROS job"
.\run.ps1 worker
# Терминал 3
.\run.ps1 node -Frames 2
# Терминал 4: затем нажать пробел для старта воспроизведения
.\run.ps1 bag
```

Worker по умолчанию использует **CPU INT8**, ширину 280 и один набор кадров.
При старте требуется минимум 3 GiB доступной RAM. После задания worker завершится
и откроет Rerun. Для повторения остановить ноду (Ctrl+C), снова запустить worker,
ноду и bag. `roscore` можно оставить запущенным.

```powershell
# Полная автоматическая репетиция; сама запускает ROS и останавливает свои процессы
.\.venv\Scripts\python.exe -X utf8 tests\rehearse_live.py
# Открыть RRD из outputs/, подставив имя созданного файла
.\.venv\Scripts\python.exe -m rerun outputs\scene_JOB_ID.rrd
# Остановить контейнеры проекта после занятия
.\run.ps1 stop
```

Автоматическая репетиция сохраняет `outputs/live_rehearsal.json`, проверяет
совпадение XYZ/RGBA в ROS с результатом модели и прерывается при доступной системной
RAM ниже 512 MiB. Это не измерение точности восстановления сцены.

## Сборка пакета и собственно ROS-команды

Следующие команды выполняются внутри контейнера `ros`; `run.ps1` и `run.sh`
вызывают их через `docker compose exec`:

```bash
source /opt/ros/noetic/setup.bash
cd /demo/catkin_ws
catkin_make
source devel/setup.bash
rospack find vggt_scene
```

В отдельных терминалах контейнера после `source`:

```bash
roscore
roslaunch vggt_scene scene.launch frames:=2
rosbag play --clock --pause /demo/data/nuplan_front_2hz.bag
rostopic info /vggt/points
rostopic echo -n 1 /vggt/points/header
```

Изображения приходят в callback; ограниченный набор передаётся в отдельный поток.
Нода не накапливает весь bag. `Publisher` с `latch=True` удерживает последнее облако.
Поле `header.stamp` содержит время последнего кадра, а не время завершения инференса.

## Координаты и ограничения

VGGT оценивает `p_camera = R @ p_world + t`. Поза камеры для Rerun:
`R_world_from_camera = R.T`, `camera_center_world = -R.T @ t`.
Оптические оси: x вправо, y вниз, z вперёд (`RDF`). Это не `base_link` автомобиля.

`vggt_world` имеет **неизвестный метрический масштаб**. Облако служит визуальной
демонстрацией, его нельзя напрямую использовать в метрической навигации ROS.
Два кадра дают одну локальную реконструкцию; это не SLAM всей записи. Для объединения
независимых окон нужны согласование поз и масштаба. Калибровка CameraInfo и TF к
автомобилю здесь не известны и не подставляются искусственно.

Есть простая обрезка верхних 24% изображения для дорожной сцены и отбор по confidence.
Это не семантическое выделение неба. Confidence не является сигмой в метрах.
В исходном INT8-тесте она выродилась в 1,0; качество квантования относительно FP32
не измерялось. В облаке видны искажения и двоение. На Thor начните с BF16 и двух
кадров; увеличение разрешения и числа кадров требует новых замеров памяти и качества.

## Источники и лицензии

- [VGGT — официальный код](https://github.com/facebookresearch/vggt), ревизия `a288dd0f14786c93483e45524328726ab7b1b4ce`. Скрипт сохраняет upstream LICENSE рядом с кодом.
- [VGGT-1B — официальные веса](https://huggingface.co/facebook/VGGT-1B), ревизия `860abec7937da0a4c03c41d3c269c366e82abdf9`; checkpoint CC BY-NC 4.0.
- [Rerun SDK 0.23.4](https://ref.rerun.io/docs/python/0.23.4/).
- [nuPlan](https://github.com/motional/nuplan-devkit): данные распространяются по условиям датасета и не входят в этот репозиторий.

Учебный код ROS-пакета и обвязки — [MIT](LICENSE). Это не меняет лицензии VGGT,
весов, контейнеров и датасетов.
