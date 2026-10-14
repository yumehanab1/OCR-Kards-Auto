import numpy as np

class OrtInferSession:
    def __init__(self,config):
        self.infer=config['infer']
        self.model=config['model']
        self.characters=config.get('characters')
    def __call__(self,array):return [self.infer(self.model,np.asarray(array,dtype=np.float32))]
    def have_key(self):return self.characters is not None
    def get_character_list(self):return list(self.characters)

def read_yaml(path):raise ValueError('native_ocr_uses_packaged_json_config')
