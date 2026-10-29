import unittest

from realtime_service.outreach import create_draft


class OutreachTests(unittest.TestCase):
    def test_marketplace_clothing_brand(self):
        draft = create_draft({
            "category": "presentations",
            "buyer": "",
            "body": "Waistline (российский бренд женской одежды) ищет дизайнера для Wildberries и Ozon. "
                    "Создание обложек, инфографики и слайдов карточек. Figma. Удалённо."
        })
        self.assertIn("Waistline", draft)
        self.assertIn("маркетплейсов", draft)
        self.assertIn("инфографику", draft)
        self.assertIn("Avito", draft)
        self.assertNotIn("директор", draft.lower())

    def test_tilda_landing(self):
        draft = create_draft({
            "category": "web",
            "body": "Требуется разработка лендинга на Tilda: 6-9 блоков и мобильная версия."
        })
        self.assertIn("лендинг на Tilda", draft)
        self.assertIn("адаптивный", draft)
        self.assertNotIn("Увидел объём", draft)

    def test_ui_ux(self):
        draft = create_draft({
            "category": "uiux",
            "body": "UX аудит экрана iOS, дизайн-система, компоненты в Figma"
        })
        self.assertIn("UX-аудит", draft)
        self.assertIn("систему компонентов", draft)
        self.assertIn("Figma", draft)

    def test_presentation_specific_scope(self):
        draft = create_draft({
            "category": "presentations",
            "body": "Нужно оформить презентацию на 140 слайдов, инфографика, презентация"
        })
        self.assertIn("140 слайдов", draft)
        self.assertIn("Haval", draft)

    def test_branding(self):
        draft = create_draft({
            "category": "branding",
            "buyer": "Клиент",
            "body": "Ищем дизайнера: ребрендинг строительной компании, фирменный стиль."
        })
        self.assertIn("фирменному стилю", draft)
        self.assertIn("Портфолио: https://samsel.site", draft)

    def test_never_claims_to_have_sent(self):
        draft = create_draft({"category": "web", "body": "Сайт на WordPress"})
        self.assertNotIn("отправлено", draft.lower())
        self.assertIn("задача ещё актуальна", draft)


if __name__ == "__main__":
    unittest.main()
