"""База упражнений (раздел 3.4.1, 6.1): не меньше 70 для зала, 35 для площадки и 15 с резинкой.

Загружается в общий каталог при старте бота (повторно — без дублей). Строка: ключ, название, место, оборудование,
группа, основная мышца, вторичные, движение, базовое (B) / изолирующее (I), сложность, измерение, флаги.
Флаги: ``floor`` — лёжа на земле, ``m`` / ``f`` — предлагать только мужчинам / женщинам, ``loaded`` — отягощение,
``each`` — вес каждой гантели, ``step=2.5``, ``reps=6-8``, ``easier=…``, ``harder=…``.
"""

from __future__ import annotations

from decimal import Decimal

from habit_bot.modules.workouts.domain.training import (
    Difficulty,
    Equipment,
    ExerciseSpec,
    Group,
    Measure,
    Movement,
    Muscle,
    Place,
    Suggest,
)

_PLACE = {"зал": Place.GYM, "улица": Place.OUTDOOR, "везде": Place.ANY}
_EQUIP = {
    "штанга": Equipment.BARBELL, "гантели": Equipment.DUMBBELL, "тренажёр": Equipment.MACHINE, "блок": Equipment.CABLE,
    "гиря": Equipment.KETTLEBELL, "турник": Equipment.PULLUP_BAR, "брусья": Equipment.DIP_BARS,
    "перекладина": Equipment.LOW_BAR, "стенка": Equipment.WALL_BARS, "лавка": Equipment.BENCH,
    "рукоход": Equipment.MONKEY_BARS, "резинка": Equipment.BAND, "—": Equipment.NONE,
}
_MUSCLE = {
    "квадрицепс": Muscle.QUADS, "бицепс бедра": Muscle.HAMSTRINGS, "ягодицы": Muscle.GLUTES, "икры": Muscle.CALVES,
    "грудь": Muscle.CHEST, "спина": Muscle.BACK, "плечи": Muscle.SHOULDERS, "бицепс": Muscle.BICEPS,
    "трицепс": Muscle.TRICEPS, "предплечья": Muscle.FOREARMS, "кор": Muscle.CORE,
}
_MOVE = {
    "присед": Movement.SQUAT, "наклон": Movement.HINGE, "выпад": Movement.LUNGE, "г-жим": Movement.H_PUSH,
    "в-жим": Movement.V_PUSH, "г-тяга": Movement.H_PULL, "в-тяга": Movement.V_PULL, "кор": Movement.CORE,
    "изол": Movement.ISOLATION,
}
_DIFF = {"нов": Difficulty.BEGINNER, "сред": Difficulty.INTERMEDIATE, "прод": Difficulty.ADVANCED}
_MEAS = {"вес": Measure.WEIGHT_REPS, "повт": Measure.REPS, "время": Measure.TIME, "рез": Measure.BAND_REPS}
_GROUP = {g.value: g for g in Group}

# ключ | название | место | оборудование | группа | основная | вторичные | движение | B/I | сложность | измерение | флаги
_ROWS = """
back_squat | Присед со штангой | зал | штанга | legs | квадрицепс | ягодицы,кор | присед | B | сред | вес | step=2.5 reps=6-8 easier=goblet_squat harder=front_squat
front_squat | Фронтальный присед | зал | штанга | legs | квадрицепс | ягодицы,кор | присед | B | прод | вес | step=2.5 reps=6-8 easier=back_squat
goblet_squat | Гоблет-присед | зал | гантели | legs | квадрицепс | ягодицы | присед | B | нов | вес | step=2 reps=8-12 harder=back_squat
leg_press | Жим ногами | зал | тренажёр | legs | квадрицепс | ягодицы | присед | B | нов | вес | step=5 reps=10-12
hack_squat | Гакк-присед | зал | тренажёр | legs | квадрицепс | ягодицы | присед | B | сред | вес | step=5 reps=8-12
db_lunges | Выпады с гантелями | зал | гантели | legs | квадрицепс | ягодицы | выпад | B | сред | вес | step=2 reps=8-12 each
bulgarian_db | Болгарские сплит-приседы с гантелями | зал | гантели | legs | квадрицепс | ягодицы | выпад | B | сред | вес | step=2 reps=8-12 each easier=bulgarian_split
walking_lunges_bb | Выпады со штангой | зал | штанга | legs | квадрицепс | ягодицы | выпад | B | прод | вес | step=2.5 reps=8-10
leg_extension | Разгибания ног в тренажёре | зал | тренажёр | legs | квадрицепс | — | изол | I | нов | вес | step=5 reps=12-15
leg_curl | Сгибания ног в тренажёре | зал | тренажёр | legs | бицепс бедра | — | изол | I | нов | вес | step=5 reps=10-15
calf_raise_machine | Подъёмы на носки в тренажёре | зал | тренажёр | legs | икры | — | изол | I | нов | вес | step=5 reps=12-20
seated_calf | Подъёмы на носки сидя | зал | тренажёр | legs | икры | — | изол | I | нов | вес | step=5 reps=12-20
hip_abduction | Отведение бедра в тренажёре | зал | тренажёр | legs | ягодицы | — | изол | I | нов | вес | step=5 reps=12-20 f
hip_adduction | Сведение бедра в тренажёре | зал | тренажёр | legs | квадрицепс | — | изол | I | нов | вес | step=5 reps=12-20 f
smith_squat | Присед в Смите | зал | тренажёр | legs | квадрицепс | ягодицы | присед | B | нов | вес | step=2.5 reps=8-12
step_up_db | Зашагивания на лавку с гантелями | зал | гантели | legs | квадрицепс | ягодицы | выпад | B | нов | вес | step=2 reps=10-12 each
romanian_deadlift | Румынская тяга | зал | штанга | hinge | бицепс бедра | ягодицы,спина | наклон | B | сред | вес | step=2.5 reps=8-10
deadlift | Становая тяга | зал | штанга | hinge | спина | ягодицы,бицепс бедра | наклон | B | прод | вес | step=5 reps=4-6
hip_thrust | Ягодичный мост со штангой | зал | штанга | hinge | ягодицы | бицепс бедра | наклон | B | сред | вес | step=5 reps=8-12
hyperextension | Гиперэкстензия | зал | тренажёр | hinge | спина | ягодицы,бицепс бедра | наклон | I | нов | повт | reps=12-15
kb_swing | Тяга с гирей (свинг) | зал | гиря | hinge | ягодицы | бицепс бедра,кор | наклон | B | сред | вес | step=4 reps=12-20
db_rdl | Румынская тяга с гантелями | зал | гантели | hinge | бицепс бедра | ягодицы | наклон | B | нов | вес | step=2 reps=10-12 each
bench_press | Жим лёжа | зал | штанга | chest | грудь | трицепс,плечи | г-жим | B | сред | вес | step=2.5 reps=6-8
incline_bench | Жим штанги на наклонной | зал | штанга | chest | грудь | плечи,трицепс | г-жим | B | сред | вес | step=2.5 reps=6-10
incline_db | Жим гантелей на наклонной | зал | гантели | chest | грудь | плечи,трицепс | г-жим | B | сред | вес | step=2 reps=8-12 each
db_bench | Жим гантелей лёжа | зал | гантели | chest | грудь | трицепс,плечи | г-жим | B | нов | вес | step=2 reps=8-12 each
dips_gym | Отжимания на брусьях | зал | брусья | chest | грудь | трицепс | г-жим | B | сред | повт | reps=6-12
cable_fly | Сведения в кроссовере | зал | блок | chest | грудь | — | изол | I | нов | вес | step=2.5 reps=12-15
pec_deck | Бабочка | зал | тренажёр | chest | грудь | — | изол | I | нов | вес | step=5 reps=12-15
chest_press_machine | Жим от груди в тренажёре | зал | тренажёр | chest | грудь | трицепс | г-жим | B | нов | вес | step=5 reps=10-12
db_fly | Разводка гантелей лёжа | зал | гантели | chest | грудь | — | изол | I | нов | вес | step=2 reps=12-15 each
pushup_gym | Отжимания от пола | везде | — | chest | грудь | трицепс,кор | г-жим | B | нов | повт | floor reps=10-20
barbell_row | Тяга штанги в наклоне | зал | штанга | back | спина | бицепс | г-тяга | B | сред | вес | step=2.5 reps=8-10
db_row | Тяга гантели одной рукой | зал | гантели | back | спина | бицепс | г-тяга | B | нов | вес | step=2 reps=8-12
lat_pulldown | Тяга верхнего блока | зал | блок | back | спина | бицепс | в-тяга | B | нов | вес | step=5 reps=8-12
seated_row | Тяга нижнего блока | зал | блок | back | спина | бицепс | г-тяга | B | нов | вес | step=5 reps=8-12
pullup_gym | Подтягивания | зал | турник | back | спина | бицепс | в-тяга | B | сред | повт | reps=5-10
cable_pullover | Пуловер в блоке | зал | блок | back | спина | — | изол | I | сред | вес | step=2.5 reps=12-15
bb_shrug | Шраги со штангой | зал | штанга | back | спина | — | изол | I | нов | вес | step=5 reps=10-15 m
db_shrug | Шраги с гантелями | зал | гантели | back | спина | — | изол | I | нов | вес | step=2 reps=10-15 m each
tbar_row | Тяга Т-грифа | зал | штанга | back | спина | бицепс | г-тяга | B | сред | вес | step=2.5 reps=8-10
machine_row | Тяга в тренажёре сидя | зал | тренажёр | back | спина | бицепс | г-тяга | B | нов | вес | step=5 reps=10-12
overhead_press | Жим стоя | зал | штанга | shoulders | плечи | трицепс,кор | в-жим | B | сред | вес | step=2.5 reps=6-8
seated_db_press | Жим гантелей сидя | зал | гантели | shoulders | плечи | трицепс | в-жим | B | нов | вес | step=2 reps=8-12 each
lateral_raise | Махи в стороны | зал | гантели | shoulders | плечи | — | изол | I | нов | вес | step=1 reps=12-15 each
rear_delt_raise | Махи в наклоне | зал | гантели | shoulders | плечи | спина | изол | I | нов | вес | step=1 reps=12-15 each
face_pull | Тяга к лицу | зал | блок | shoulders | плечи | спина | г-тяга | I | нов | вес | step=2.5 reps=12-15
upright_row | Тяга штанги к подбородку | зал | штанга | shoulders | плечи | спина | изол | I | сред | вес | step=2.5 reps=10-12 m
machine_press | Жим вверх в тренажёре | зал | тренажёр | shoulders | плечи | трицепс | в-жим | B | нов | вес | step=5 reps=10-12
bb_curl | Сгибания со штангой | зал | штанга | arms | бицепс | предплечья | изол | I | нов | вес | step=2.5 reps=8-12
db_curl | Сгибания с гантелями | зал | гантели | arms | бицепс | предплечья | изол | I | нов | вес | step=1 reps=10-12 each
hammer_curl | Молотковые сгибания | зал | гантели | arms | бицепс | предплечья | изол | I | нов | вес | step=1 reps=10-12 each
scott_curl | Сгибания на скамье Скотта | зал | штанга | arms | бицепс | — | изол | I | сред | вес | step=2.5 reps=10-12
cable_curl | Сгибания на блоке | зал | блок | arms | бицепс | — | изол | I | нов | вес | step=2.5 reps=12-15
pushdown | Разгибания на блоке | зал | блок | arms | трицепс | — | изол | I | нов | вес | step=2.5 reps=10-15
french_press | Французский жим | зал | штанга | arms | трицепс | — | изол | I | сред | вес | step=2.5 reps=8-12
overhead_ext | Разгибания над головой с гантелью | зал | гантели | arms | трицепс | — | изол | I | нов | вес | step=2 reps=10-12
close_grip_bench | Жим узким хватом | зал | штанга | arms | трицепс | грудь | г-жим | B | сред | вес | step=2.5 reps=6-10
wrist_curl | Сгибания запястий | зал | гантели | arms | предплечья | — | изол | I | нов | вес | step=1 reps=15-20 each
hanging_leg_raise_gym | Подъём ног в висе | зал | турник | core | кор | — | кор | I | сред | повт | reps=8-15
cable_crunch | Скручивания в блоке | зал | блок | core | кор | — | кор | I | нов | вес | step=2.5 reps=12-15
plank | Планка | везде | — | core | кор | плечи | кор | I | нов | время | floor reps=30-90
ab_wheel | «Колесо» | везде | — | core | кор | плечи | кор | B | прод | повт | floor reps=8-12
pallof_cable | Паллоф-пресс в блоке | зал | блок | core | кор | — | кор | I | нов | вес | step=2.5 reps=10-12
crunches | Скручивания | везде | — | core | кор | — | кор | I | нов | повт | floor reps=15-25
side_plank | Боковая планка | везде | — | core | кор | — | кор | I | нов | время | floor reps=20-60
dead_hang | Вис на турнике | улица | турник | bar | предплечья | спина | в-тяга | I | нов | время | reps=20-60 harder=negative_pullup
negative_pullup | Негативные подтягивания | улица | турник | bar | спина | бицепс | в-тяга | B | нов | повт | reps=3-6 easier=dead_hang harder=pullup_wide
pullup_wide | Подтягивания широким хватом | улица | турник | bar | спина | бицепс | в-тяга | B | сред | повт | reps=5-10 easier=negative_pullup harder=weighted_pullup
pullup_straight | Подтягивания прямым хватом | улица | турник | bar | спина | бицепс | в-тяга | B | сред | повт | reps=5-10
chinup | Подтягивания обратным хватом | улица | турник | bar | бицепс | спина | в-тяга | B | сред | повт | reps=5-10
pullup_close | Подтягивания узким хватом | улица | турник | bar | спина | бицепс | в-тяга | B | сред | повт | reps=5-10
australian_pullup | Австралийские подтягивания | улица | перекладина | bar | спина | бицепс | г-тяга | B | нов | повт | reps=8-15 harder=negative_pullup
hanging_knee_raise | Подъём коленей в висе | улица | турник | bar | кор | — | кор | I | нов | повт | reps=8-15 harder=hanging_leg_raise
hanging_leg_raise | Подъём ног в висе на турнике | улица | турник | bar | кор | — | кор | I | сред | повт | reps=6-12 easier=hanging_knee_raise
monkey_bars | Рукоход | улица | рукоход | bar | спина | предплечья | в-тяга | B | сред | повт | reps=1-5
weighted_pullup | Подтягивания с отягощением | улица | турник | bar | спина | бицепс | в-тяга | B | прод | вес | loaded step=2.5 reps=4-8 easier=pullup_wide
dip_support | Упор на брусьях | улица | брусья | dips | трицепс | плечи | в-жим | I | нов | время | reps=10-30 harder=dip_negative
dip_negative | Негативные отжимания на брусьях | улица | брусья | dips | трицепс | грудь | г-жим | B | нов | повт | reps=3-6 easier=dip_support harder=dips
dips | Отжимания на брусьях на улице | улица | брусья | dips | грудь | трицепс | г-жим | B | сред | повт | reps=6-12 easier=dip_negative
dip_knee_raise | Подъём коленей в упоре на брусьях | улица | брусья | dips | кор | — | кор | I | нов | повт | reps=8-15
dips_straight | Отжимания на прямых брусьях | улица | брусья | dips | трицепс | грудь | г-жим | B | прод | повт | reps=5-10
bench_pushup | Отжимания от лавки | улица | лавка | bench | грудь | трицепс | г-жим | B | нов | повт | reps=10-20 harder=decline_pushup
decline_pushup | Отжимания с ногами на лавке | улица | лавка | bench | грудь | плечи | г-жим | B | сред | повт | reps=8-15 easier=bench_pushup
bench_dips | Обратные отжимания от лавки | улица | лавка | bench | трицепс | плечи | в-жим | B | нов | повт | reps=10-15
bulgarian_split | Болгарские сплит-приседы | улица | лавка | bench | квадрицепс | ягодицы | выпад | B | сред | повт | reps=8-12 harder=bulgarian_db
step_up | Зашагивания на лавку | улица | лавка | bench | квадрицепс | ягодицы | выпад | B | нов | повт | reps=10-15
wall_leg_raise | Подъём ног на шведской стенке | улица | стенка | bench | кор | — | кор | I | сред | повт | reps=8-12
wall_squat_assist | Приседания с опорой о стенку | улица | стенка | bench | квадрицепс | ягодицы | присед | B | нов | повт | reps=10-15 harder=pistol_assist
incline_pushup_bar | Отжимания от низкой перекладины | улица | перекладина | bench | грудь | трицепс | г-жим | B | нов | повт | reps=10-20 harder=bench_pushup
air_squat | Приседания | улица | — | standing | квадрицепс | ягодицы | присед | B | нов | повт | reps=15-25 harder=pause_squat
walking_lunge | Выпады шагами | улица | — | standing | квадрицепс | ягодицы | выпад | B | нов | повт | reps=10-16
reverse_lunge | Выпады назад | улица | — | standing | квадрицепс | ягодицы | выпад | B | нов | повт | reps=10-16
pause_squat | Приседания с паузой | улица | — | standing | квадрицепс | ягодицы | присед | B | сред | повт | reps=10-15 easier=air_squat harder=pistol_assist
pistol_assist | Пистолет с опорой | улица | — | standing | квадрицепс | ягодицы | присед | B | прод | повт | reps=4-8 easier=pause_squat
step_calf_raise | Подъёмы на носки на ступеньке | улица | — | standing | икры | — | изол | I | нов | повт | reps=15-25
jumps | Прыжки | улица | — | standing | квадрицепс | икры | присед | B | сред | повт | reps=8-15
jump_lunge | Выпады в прыжке | улица | — | standing | квадрицепс | ягодицы | выпад | B | прод | повт | reps=8-12
band_pullup | Подтягивания с резинкой | улица | резинка | band | спина | бицепс | в-тяга | B | нов | рез | reps=5-10 harder=negative_pullup
band_face_pull | Тяга резины к лицу | везде | резинка | band | плечи | спина | г-тяга | I | нов | рез | reps=12-20
band_row | Тяга резины к поясу | везде | резинка | band | спина | бицепс | г-тяга | B | нов | рез | reps=12-15
band_pulldown | Тяга резины сверху вниз | везде | резинка | band | спина | бицепс | в-тяга | B | нов | рез | reps=12-15
band_lateral | Махи с резинкой | везде | резинка | band | плечи | — | изол | I | нов | рез | reps=12-20
band_curl | Сгибания с резинкой | везде | резинка | band | бицепс | — | изол | I | нов | рез | reps=12-20
band_overhead_ext | Разгибания над головой с резинкой | везде | резинка | band | трицепс | — | изол | I | нов | рез | reps=12-20
band_pushup | Отжимания с резинкой | везде | резинка | band | грудь | трицепс | г-жим | B | сред | рез | floor reps=8-15
band_pallof | Паллоф-пресс с резинкой | везде | резинка | band | кор | — | кор | I | нов | рез | reps=10-12
band_kickback | Отведение ноги стоя с резинкой | везде | резинка | band | ягодицы | — | изол | I | нов | рез | reps=12-20
band_squat | Приседания с резинкой | везде | резинка | band | квадрицепс | ягодицы | присед | B | нов | рез | reps=12-20
band_good_morning | Наклоны с резинкой | везде | резинка | band | бицепс бедра | спина | наклон | B | нов | рез | reps=12-15
band_press | Жим резины стоя | везде | резинка | band | плечи | трицепс | в-жим | B | нов | рез | reps=10-15
band_pull_apart | Разведение резины перед собой | везде | резинка | band | плечи | спина | г-тяга | I | нов | рез | reps=15-25
band_chest_press | Жим резины от груди стоя | везде | резинка | band | грудь | трицепс | г-жим | B | нов | рез | reps=12-15
band_hip_abduction | Шаги в сторону с резинкой | везде | резинка | band | ягодицы | — | изол | I | нов | рез | reps=12-20
band_glute_bridge | Ягодичный мост с резинкой | везде | резинка | band | ягодицы | бицепс бедра | наклон | I | нов | рез | floor reps=15-20
band_dips_assist | Отжимания на брусьях с резинкой | улица | резинка | band | грудь | трицепс | г-жим | B | нов | рез | reps=6-10 harder=dips
glute_bridge_floor | Ягодичный мост на полу | везде | — | hinge | ягодицы | бицепс бедра | наклон | I | нов | повт | floor reps=15-20
assisted_pullup | Подтягивания в гравитроне | зал | тренажёр | back | спина | бицепс | в-тяга | B | нов | вес | step=5 reps=8-12 harder=pullup_gym
machine_curl | Сгибания рук в тренажёре | зал | тренажёр | arms | бицепс | — | изол | I | нов | вес | step=5 reps=10-15
arnold_press | Жим Арнольда | зал | гантели | shoulders | плечи | трицепс | в-жим | B | сред | вес | step=2 reps=8-12 each
one_arm_hang | Вис на одной руке | улица | турник | bar | предплечья | спина | в-тяга | I | прод | время | reps=10-30 easier=dead_hang
pause_pullup | Подтягивания с паузой вверху | улица | турник | bar | спина | бицепс | в-тяга | B | прод | повт | reps=3-6 easier=pullup_wide
muscle_up | Подъём с переворотом | улица | турник | bar | спина | бицепс,кор | в-тяга | B | прод | повт | reps=1-5 easier=pullup_wide
box_jump | Запрыгивания на лавку | улица | лавка | bench | квадрицепс | икры | присед | B | сред | повт | reps=8-12
cable_kickback | Отведение ноги назад в кроссовере | зал | блок | legs | ягодицы | — | изол | I | нов | вес | step=2.5 reps=12-15 f
"""


def _parse(line: str) -> ExerciseSpec:
    (key, name, place, equip, group, primary, secondary, move, kind, diff, measure, *rest) = [
        p.strip() for p in line.split("|")]
    flags = rest[0].split() if rest else []
    options: dict[str, str] = dict(f.split("=", 1) for f in flags if "=" in f)
    low, _, high = options.get("reps", "8-12").partition("-")
    suggest = Suggest.MEN if "m" in flags else Suggest.WOMEN if "f" in flags else Suggest.ALL
    return ExerciseSpec(
        key=key, name=name, place=_PLACE[place], equipment=_EQUIP[equip], group=_GROUP[group],
        primary=_MUSCLE[primary],
        secondary=tuple(_MUSCLE[m] for m in secondary.split(",") if m != "—"),
        movement=_MOVE[move], compound=kind == "B", difficulty=_DIFF[diff], measure=_MEAS[measure],
        floor="floor" in flags, suggest=suggest, loaded="loaded" in flags, easier=options.get("easier"),
        harder=options.get("harder"), weight_step=Decimal(options["step"]) if "step" in options else None,
        reps_low=int(low), reps_high=int(high or low), per_dumbbell="each" in flags,
    )


EXERCISES: tuple[ExerciseSpec, ...] = tuple(_parse(line) for line in _ROWS.strip().splitlines())
BY_KEY = {e.key: e for e in EXERCISES}
