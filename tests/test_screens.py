"""M1.6 pure private-screen rendering contracts."""

import copy
import importlib
import unittest
from unittest.mock import patch

from pokewalker.services.profiles import Restrictions


class ScreenTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        try:
            self.screens = importlib.import_module("pokewalker.bot.screens")
        except ModuleNotFoundError:
            self.fail("M1.6 screen renderers are absent")
        self.state = {"session": {"session_id": "abcd", "revision": 2},
                      "companion": {"name": "Bulbasaur", "cp": 123, "sprite": "https://exact/sprite.png"},
                      "queue_size": 0, "encounter_meter_c": 2500, "restrictions": Restrictions()}

    async def test_home_queue_count_and_disabled_button(self):
        for count in (0, 1, 3):
            self.state["queue_size"] = count
            rendered = self.screens.home(self.state)
            self.assertIn(f"{count}/3", rendered["embed"].description)
            self.assertIn("Bulbasaur", rendered["embed"].description)
            self.assertIn("123", rendered["embed"].description)
            self.assertIn("25/100", rendered["embed"].description)
            buttons = rendered["view"].children
            self.assertEqual(buttons[0].label, "Open encounter")
            self.assertEqual(buttons[0].disabled, count == 0)
            self.assertTrue(all(button.disabled for button in buttons[1:]))
            self.assertEqual([button.label for button in buttons[1:]], ["Storage", "Bag", "Pokédex", "Route", "Gyms", "Arena", "Inbox (0)"])
            self.assertTrue(all(button.custom_id.startswith("pw:v1:abcd:2:") for button in buttons))

    async def test_home_has_gyms_button_enabled_when_registered(self):
        rendered = self.screens.home({**self.state, 'available': {'gyms'}})
        button = next(b for b in rendered['view'].children if b.label == 'Gyms')
        self.assertFalse(button.disabled)
        self.assertEqual(button.custom_id, 'pw:v1:abcd:2:gyms')

    async def test_home_has_arena_button_enabled_only_when_registered(self):
        for available in (set(), {'gyms'}, {'arena'}, {'gyms', 'arena'}):
            rendered = self.screens.home({**self.state, 'available': available})
            buttons = rendered['view'].children
            arena = [button for button in buttons if button.label == 'Arena']
            self.assertEqual(len(arena), 1)
            self.assertEqual(arena[0].disabled, 'arena' not in available)
            self.assertEqual(arena[0].custom_id, 'pw:v1:abcd:2:arena')
            self.assertEqual(buttons.index(arena[0]), next(i for i, button in enumerate(buttons) if button.label == 'Gyms') + 1)
            self.assertLessEqual(len(rendered['view'].to_components()), 5)

    async def test_home_gyms_button_disabled_when_handler_absent(self):
        for changes in ({}, {'available': {'storage'}}):
            rendered = self.screens.home({**self.state, **changes})
            button = next(b for b in rendered['view'].children if b.label == 'Gyms')
            self.assertTrue(button.disabled)

    async def test_home_view_within_5_rows(self):
        components = self.screens.home(self.state)['view'].to_components()
        self.assertLessEqual(len(components), 5)
        self.assertTrue(all(len(row['components']) <= 5 for row in components))
        self.assertEqual(sum(len(row['components']) for row in components), 8)

    async def test_home_inbox_button_shows_waiting_count_disabled_at_zero(self):
        for waiting, disabled in ((2, False), (0, True)):
            rendered = self.screens.home({**self.state, "rewards_waiting": waiting, "available": {"inbox"}})
            button = next(b for b in rendered["view"].children if b.label.startswith("Inbox"))
            self.assertEqual((button.label, button.disabled), (f"Inbox ({waiting})", disabled))
            self.assertTrue(button.custom_id.endswith(":inbox"))

    async def test_home_thumbnail_exact_sprite_or_none(self):
        for sprite in ("https://exact/shiny-female.png", None):
            self.state["companion"]["sprite"] = sprite
            self.assertEqual(self.screens.home(self.state)["embed"].thumbnail.url, sprite)

    async def test_render_functions_do_no_io(self):
        self.state.update(generations=list(range(1, 10)), starters=[{"species_id": n, "name": str(n)} for n in (1, 4, 7)])
        original = copy.deepcopy(self.state)
        with patch("builtins.open", side_effect=AssertionError("render opened a file")), \
                patch("aiosqlite.connect", side_effect=AssertionError("render opened DB")):
            self.screens.home(self.state)
            rendered = self.screens.onboarding(self.state)
            self.assertLessEqual(len(rendered["embed"].description.splitlines()), 6)
            self.assertEqual(len(rendered["view"].children[0].options), 9)
            self.state["selection"] = {"generation": 1}
            self.assertEqual(len(self.screens.onboarding(self.state)["view"].children[0].options), 3)
            self.state.pop("selection")
        self.assertEqual(self.state, original)

    async def test_every_screen_view_has_unique_custom_ids(self):
        state = dict(self.state, generations=[1], starters=[{"species_id": 1, "name": "Bulbasaur"}],
                     encounter={"gender": "male", "shiny": False, "tier": "common", "state": "caught",
                                "iv_attack": 1, "iv_defense": 1, "iv_stamina": 1},
                     identity={"kind": "default", "name_en": "Bulbasaur", "types": ["grass"]},
                     cp=123, sprite=None, bag={"poke_ball": 1}, balls=["poke_ball"],
                     berries=["razz_berry"], selection={})
        cases = [("home", self.screens.home, {}),
                 ("onboarding generation", self.screens.onboarding, {}),
                 ("onboarding starter", self.screens.onboarding, {"selection": {"generation": 1}}),
                 ("onboarding confirm", self.screens.onboarding, {"selection": {"starter": 1}}),
                 ("catch", self.screens.render_catch, {}),
                 ("ball picker", self.screens.render_catch, {"picker": "ball"}),
                 ("berry picker", self.screens.render_catch, {"picker": "berry"}),
                 ("run confirm", self.screens.render_run_confirm, {}),
                 ("terminal", self.screens.render_terminal, {}),
                 ("terminal recovery", self.screens.render_terminal, {"recovery": True}),
                 ("master confirm", self.screens.render_master_confirm, {})]
        for name, render, changes in cases:
            with self.subTest(screen=name):
                view = render({**state, **changes})["view"]
                ids = [item.custom_id for item in view.children if item.custom_id is not None]
                self.assertEqual(len(ids), len(set(ids)), ids)

    async def test_catch_pickers_show_only_stock_and_always_allow_no_berry(self):
        state = dict(self.state, encounter={"gender": "male", "shiny": False, "tier": "common"},
                     identity={"kind": "default", "name_en": "Bulbasaur", "types": ["grass"]},
                     cp=123, sprite=None, balls=["poke_ball", "great_ball", "master_ball"],
                     berries=["razz_berry", "pinap_berry"], selection={},
                     bag={"poke_ball": 2, "great_ball": 0, "razz_berry": 1, "pinap_berry": 0})
        ball = self.screens.render_catch({**state, "picker": "ball"})["view"]
        self.assertEqual([option.value for option in ball.children[-1].options], ["poke_ball"])
        self.assertFalse(ball.children[0].disabled)
        berry = self.screens.render_catch({**state, "picker": "berry"})["view"]
        self.assertEqual([option.value for option in berry.children[-1].options], ["none", "razz_berry"])
        empty = {**state, "bag": {}}
        ball = self.screens.render_catch({**empty, "picker": "ball"})["view"]
        self.assertTrue(ball.children[0].disabled)
        self.assertFalse(any(hasattr(item, "options") for item in ball.children))
        berry = self.screens.render_catch({**empty, "picker": "berry"})["view"]
        self.assertEqual([option.value for option in berry.children[-1].options], ["none"])
