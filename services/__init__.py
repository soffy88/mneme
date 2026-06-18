import oprim.types
oprim.types.KCState.p_recognition = None
oprim.types.KCState.p_recognition_init = 0.20

original_kc_init = oprim.types.KCState.__init__
def _new_kc_init(self, *args, **kwargs):
    p_rec = kwargs.pop('p_recognition', None)
    p_rec_init = kwargs.pop('p_recognition_init', 0.20)
    original_kc_init(self, *args, **kwargs)
    # Since KCState might be frozen or non-frozen, we use object.__setattr__ to be safe
    object.__setattr__(self, 'p_recognition', p_rec)
    object.__setattr__(self, 'p_recognition_init', p_rec_init)
oprim.types.KCState.__init__ = _new_kc_init

original_grade_init = oprim.types.GradeResult.__init__
def _new_grade_init(self, *args, **kwargs):
    reason = kwargs.pop('reason', None)
    original_grade_init(self, *args, **kwargs)
    object.__setattr__(self, 'reason', reason)
oprim.types.GradeResult.__init__ = _new_grade_init
