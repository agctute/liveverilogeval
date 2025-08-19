import yaml
class Config:
    def __init__(self, config_path: str="./config.yaml"):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            for key, value in config.items():
                setattr(self, key, value)