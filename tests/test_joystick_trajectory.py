import math
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from screens.joystick_trajectory_widget import FORMAS, JoystickTrajectoryWidget, reference_points


class TrajectoryReferenceTests(unittest.TestCase):
    def test_all_shapes_close_after_48_clockwise_targets(self):
        for shape in FORMAS:
            with self.subTest(shape=shape):
                points = reference_points(shape)
                self.assertEqual(len(points), 49)
                self.assertEqual(points[0], points[-1])
                signed_area = sum(
                    a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:])
                ) / 2
                self.assertLess(signed_area, 0, "Y-up coordinates must wind clockwise")

    def test_square_starts_at_upper_left_and_matches_firmware_vertices(self):
        points = reference_points("QUADRADO")
        self.assertEqual([points[i] for i in (0, 12, 24, 36)],
                         [(-0.75, 0.75), (0.75, 0.75), (0.75, -0.75), (-0.75, -0.75)])
        self.assertEqual(points[1], (-0.625, 0.75))

    def test_triangle_has_equilateral_vertices_and_starts_at_top(self):
        points = reference_points("TRIANGULO")
        self.assertEqual(points[0], (0, 0.75))
        self.assertAlmostEqual(points[16][0], math.sqrt(3) / 2 * 0.75)
        self.assertEqual(points[16][1], -0.375)
        self.assertAlmostEqual(points[32][0], -math.sqrt(3) / 2 * 0.75)

    def test_circle_starts_at_top_and_uses_firmware_radius(self):
        points = reference_points("CIRCULO")
        self.assertEqual(points[0], (0, 0.75))
        self.assertAlmostEqual(points[12][0], 0.75)
        self.assertAlmostEqual(points[12][1], 0)
        for point in points:
            self.assertAlmostEqual(math.hypot(*point), 0.75)

    def test_unknown_shape_has_no_reference(self):
        self.assertEqual(reference_points(None), [])
        self.assertEqual(reference_points("DIREITA"), [])


class TrajectoryWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_coordinate_mapping_preserves_aspect_ratio_and_upward_y(self):
        widget = JoystickTrajectoryWidget()
        for width, height in ((500, 250), (250, 500)):
            widget.resize(width, height)
            center = widget._map_point((0, 0))
            right = widget._map_point((1, 0))
            top = widget._map_point((0, 1))
            self.assertAlmostEqual(right.x() - center.x(), center.y() - top.y())
            self.assertLess(top.y(), center.y())
        widget.close()

    def test_samples_are_optional_and_nonfinite_positions_are_ignored(self):
        widget = JoystickTrajectoryWidget()
        widget.set_trajectory("CIRCULO", [{"x": 0.2, "y": 0.5}, {"x": math.nan, "y": 0}, {}])
        self.assertEqual(widget._samples, [(0.2, 0.5)])
        self.assertIn("após a coleta", widget.accessibleDescription())
        self.assertFalse(widget.grab().isNull())
        widget.set_trajectory("QUADRADO")
        self.assertEqual(widget._samples, [])
        self.assertIn("sem posição ao vivo", widget.accessibleDescription())
        widget.close()

    @staticmethod
    def position(**changes):
        return {
            "forma": "QUADRADO", "fase": "PERCURSO", "t_ms": 1200,
            "x": 0.1, "y": 0.2, "alvo_x": 0.75, "alvo_y": 0.75,
            "passo": 12, "progresso": 23, **changes,
        }

    def test_live_cursor_and_target_follow_received_positions(self):
        widget = JoystickTrajectoryWidget()
        widget.resize(430, 240)
        widget.set_trajectory("QUADRADO")
        widget.set_live_position(self.position())
        first = widget.grab().toImage()
        self.assertEqual(widget._live_position["x"], 0.1)
        self.assertEqual(widget._live_position["alvo_y"], 0.75)
        self.assertIn("Posição recebida", widget.accessibleDescription())
        widget.set_live_position(self.position(x=-0.6, y=-0.3, alvo_x=-0.75, alvo_y=-0.75))
        second = widget.grab().toImage()
        self.assertNotEqual(first, second)
        self.assertEqual(widget._live_position["x"], -0.6)
        self.assertEqual(widget._live_position["alvo_y"], -0.75)
        self.assertEqual(widget._samples, [], "Cursor updates must not invent a sampled trace")
        widget.close()

    def test_live_positive_y_maps_up_for_both_cursor_and_target(self):
        widget = JoystickTrajectoryWidget()
        widget.set_trajectory("QUADRADO")
        widget.set_live_position(self.position(y=0.7, alvo_y=0.75))
        p = widget._live_position
        center = widget._map_point((0, 0))
        self.assertLess(widget._map_point((p["x"], p["y"])).y(), center.y())
        self.assertLess(widget._map_point((p["alvo_x"], p["alvo_y"])).y(), center.y())
        widget.close()

    def test_clearing_live_position_removes_overlay_and_retains_record(self):
        widget = JoystickTrajectoryWidget()
        widget.set_trajectory("QUADRADO", [{"x": -0.75, "y": 0.75}, {"x": 0.75, "y": 0.75}])
        recorded = widget.grab().toImage()
        widget.set_live_position(self.position())
        self.assertIsNotNone(widget._live_position)
        widget.set_live_position(None)
        self.assertIsNone(widget._live_position)
        self.assertEqual(widget.grab().toImage(), recorded)
        self.assertEqual(len(widget._samples), 2)
        self.assertNotIn("Posição recebida", widget.accessibleDescription())
        widget.close()

    def test_changing_trajectory_removes_old_live_position(self):
        widget = JoystickTrajectoryWidget()
        widget.set_trajectory("QUADRADO")
        widget.set_live_position(self.position())
        widget.set_trajectory("CIRCULO")
        self.assertIsNone(widget._live_position)
        widget.set_live_position(self.position())
        self.assertIsNone(widget._live_position, "An old shape must not overwrite the selected shape")
        widget.close()

    def test_invalid_live_data_clears_cursor_instead_of_displaying_stale_position(self):
        widget = JoystickTrajectoryWidget()
        widget.set_trajectory("QUADRADO")
        for invalid in ({}, self.position(x=math.nan), self.position(alvo_y=math.inf),
                        self.position(y=1.01), self.position(fase="RESULTADO")):
            with self.subTest(invalid=invalid):
                widget.set_live_position(self.position())
                widget.set_live_position(invalid)
                self.assertIsNone(widget._live_position)
        widget.close()


if __name__ == "__main__":
    unittest.main()
