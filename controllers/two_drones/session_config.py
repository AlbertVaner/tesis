"""Configuracion validada de sesiones de uno o dos drones, sin hardware."""
from dataclasses import asdict, dataclass, field

GRAPH_TYPES = ('position', 'trajectory', 'latency', 'ekf', 'battery')
TARGETS = ('drone1', 'drone2', 'both')

@dataclass
class SessionConfig:
    name: str = 'Prueba Robotat'
    drones: str = 'both'
    dry_run: bool = True
    control: str = 'buttons'
    hands: str = 'two'
    single_hand: str = 'Right'
    left_target: str = 'drone1'
    right_target: str = 'drone2'
    marker_id: int = 64
    joystick_target: str = 'both'
    camera_index: int = 0
    save_csv: bool = True
    auto_graphs: bool = True
    graphs: list[str] = field(default_factory=lambda: list(GRAPH_TYPES))

    @classmethod
    def parse(cls, data, *, allow_hardware=False):
        if not isinstance(data, dict) or set(data) - set(cls.__dataclass_fields__):
            raise ValueError('Configuracion no valida')
        c = cls(**data)
        if not isinstance(c.name, str) or not c.name.strip() or len(c.name)>80:
            raise ValueError('Nombre de sesion: entre 1 y 80 caracteres')
        c.name = c.name.strip()
        for name in ('dry_run','save_csv','auto_graphs'):
            if not isinstance(getattr(c,name),bool):
                raise ValueError(f'{name} debe ser booleano')
        if not c.dry_run and not allow_hardware:
            raise ValueError('Este servidor solo permite simulacion; el modo real no esta habilitado')
        if c.drones not in TARGETS or c.joystick_target not in TARGETS:
            raise ValueError('Seleccion de drones no valida')
        if c.control not in ('buttons','hands','joystick') or c.hands not in ('one','two'):
            raise ValueError('Metodo de control no valido')
        if c.single_hand not in ('Left','Right'):
            raise ValueError('Mano no valida')
        for key in ('left_target','right_target'):
            if getattr(c,key) not in (*TARGETS,'off'):
                raise ValueError('Asignacion de mano no valida')
        for name, low, high in (('marker_id',0,65535),('camera_index',0,20)):
            value=getattr(c,name)
            if isinstance(value,bool) or not isinstance(value,int) or not low<=value<=high:
                raise ValueError(f'{name} fuera de rango')
        if not isinstance(c.graphs,list) or any(g not in GRAPH_TYPES for g in c.graphs):
            raise ValueError('Tipo de grafica no valido')
        c.graphs=list(dict.fromkeys(c.graphs))
        if c.control=='hands':
            routes=c.hand_routes()
            if not routes:
                raise ValueError('Asigna al menos una mano')
            for target in routes.values(): c.validate_target(target)
        if c.control=='joystick': c.validate_target(c.joystick_target)
        return c

    def validate_target(self,target):
        if target not in TARGETS or (self.drones!='both' and target not in (self.drones,'both')):
            raise ValueError('La orden apunta a un dron fuera de la sesion')
        return self.drones if target=='both' and self.drones!='both' else target

    def hand_routes(self):
        if self.hands=='one': return {self.single_hand:self.drones}
        return {h:t for h,t in (('Left',self.left_target),('Right',self.right_target)) if t!='off'}

    def to_dict(self): return asdict(self)
