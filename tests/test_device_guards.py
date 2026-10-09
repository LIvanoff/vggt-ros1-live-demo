"""Backend errors must be explicit, before opening weights or allocating a model."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
from inference import Reconstructor


class DeviceGuards(unittest.TestCase):
    def test_cuda_does_not_silently_fall_back_to_cpu(self):
        with patch('torch.cuda.is_available',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'CUDA unavailable'):
                Reconstructor('missing','missing',device='cuda',precision='fp32')

    def test_cpu_quantization_cannot_be_used_as_cuda_int8(self):
        with self.assertRaisesRegex(ValueError,'Supported'):
            Reconstructor('missing','missing',device='cuda',precision='int8')

    def test_bf16_requires_supported_hardware(self):
        with patch('torch.cuda.is_available',return_value=True), patch('torch.cuda.is_bf16_supported',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'does not support BF16'):
                Reconstructor('missing','missing',device='cuda',precision='bf16')

    def test_low_memory_stops_before_checkpoint_access(self):
        with patch('psutil.virtual_memory') as memory:
            memory.return_value.available=1024**3
            with self.assertRaisesRegex(RuntimeError,'No model was loaded'):
                Reconstructor('missing','missing',device='cpu',precision='int8',min_free_ram_gib=3)


if __name__=='__main__':unittest.main()
