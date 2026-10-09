param([ValidateSet('build','roscore','node','bag','worker','stop')][string]$Step='build',[int]$Frames=2)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
switch ($Step) {
 'build' {
   docker compose up -d --build ros
   if ($LASTEXITCODE -ne 0) {throw 'Docker failed'}
   docker compose exec -T ros bash -lc 'source /opt/ros/noetic/setup.bash && cd /demo/catkin_ws && catkin_make'
 }
 'roscore' { docker compose exec ros bash -lc 'source /opt/ros/noetic/setup.bash && roscore' }
 'node' {
   if ($Frames -lt 2 -or $Frames -gt 8) {throw 'Frames must be 2..8'}
   docker compose exec ros bash -lc "source /opt/ros/noetic/setup.bash && source /demo/catkin_ws/devel/setup.bash && roslaunch vggt_scene scene.launch frames:=$Frames"
 }
 'bag' { docker compose exec ros bash -lc 'source /opt/ros/noetic/setup.bash && rosbag play --clock --pause /demo/data/nuplan_front_2hz.bag' }
 'worker' { & '.\.venv\Scripts\python.exe' -X utf8 'worker\watch.py' --precision int8 --min-free-ram-gib 3 --once }
 'stop' { docker compose down }
}
if ($LASTEXITCODE -ne 0) {throw "Step failed: $Step"}
