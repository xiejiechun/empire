"""Lifecycle for independently registered desktop page providers."""


class UiPlugin:
    def __init__(self):
        self.pages = ()

    def create_pages(self):
        raise NotImplementedError

    async def start(self, context):
        self.pages = tuple(self.create_pages())
        return {self.manifest.provides[0]: self.pages}

    async def stop(self):
        self.pages = ()

    def health(self):
        return {"pages": len(self.pages)}
