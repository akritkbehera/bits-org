import os
from collections import OrderedDict

class GenerateScript:
    def __init__(self, spec: OrderedDict, template:str, specs: OrderedDict) -> None:
        self.spec = spec
        self.template = template
        self.specs = specs

    def write(self, scriptDir, generator, file:str):
        with open(os.path.join(scriptDir, file), "w") as f:
            f.write(generator())
    
    def get_template(self):
        if os.path.exists(self.template):
            with open(self.template, "r") as f:
                return f.read()
        else:
            raise Exception("Template not found at " + self.template)

    def generate_rpm_spec(self):
        Requires = ""
        for package in self.spec.get("full_requires", set()):
            if package.startswith("defaults-"):
                continue
            Requires += f"Requires: {package}_{self.specs[package]['hash']}_s{self.specs[package]['version']}_{self.specs[package]['revision']}\n"
        
        template_content = self.get_template()
        template_content = template_content.replace("(full_requires)", Requires)
        return template_content