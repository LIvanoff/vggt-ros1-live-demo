# Входной bag

Скопируйте готовый файл в `data/nuplan_front_2hz.bag`. Веса и данные не включены
в GitHub. Для занятия использовалась сцена nuPlan
`2021.09.16.19.12.04_veh-42_01088_01192_CAM_F0`:
208 JPEG, 2 Гц, 103,5 секунды между первым и последним кадрами.

Ожидаемый топик: `/camera/front/image_raw/compressed`, тип
`sensor_msgs/CompressedImage`, `format=jpeg`, `frame_id=cam_front_optical`.

## Создание из папки JPEG

`tools/images_to_bag.py` запускается внутри ROS-контейнера. В исходной папке нужен
`manifest.json` с микросекундными timestamps и относительными именами JPEG:

```json
{
  "scene_name": "my_scene",
  "frame_count": 2,
  "frames": [
    {"file": "0000.jpg", "timestamp": 1631820942499829},
    {"file": "0001.jpg", "timestamp": 1631820942999829}
  ]
}
```

Положите исходники в `data/source/`, соберите ROS-образ, затем:

```bash
docker compose run --rm ros bash -lc 'source /opt/ros/noetic/setup.bash && python3 /demo/tools/images_to_bag.py /demo/data/source /demo/data/nuplan_front_2hz.bag --hz 2'
```

JPEG сохраняются без перекодирования. Bag timestamps выравниваются на 2 Гц от
первого исходного времени. Исходные timestamps и SHA-256 сохраняются в отдельном
manifest. Существующий bag не перезаписывается. Нужны минимум два кадра; CameraInfo
и TF скрипт не создаёт.
