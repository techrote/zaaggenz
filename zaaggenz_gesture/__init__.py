"""Directionality-preserving authored gestures with source-safe compilation."""
from .model import DirectionalGesture,GestureError,VERSION,AXES,DIRECTIONS
from .transform import vary_surface,reverse_direction,replace_trajectory_points,edit_landing
from .compile import GestureCompilation,GestureRenderBundle,trajectory_value,compile_gesture,compile_gesture_recipe
from .presets import rise_turn_return

__all__=['DirectionalGesture','GestureError','VERSION','AXES','DIRECTIONS','vary_surface','reverse_direction',
         'replace_trajectory_points','edit_landing','GestureCompilation','GestureRenderBundle','trajectory_value',
         'compile_gesture','compile_gesture_recipe','rise_turn_return']
