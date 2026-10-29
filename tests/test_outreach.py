"""Regression tests: every outreach matches its actual request and does not repeat."""
import unittest
from realtime_service.outreach import analyse_brief, create_draft, valid_draft, PORTFOLIO

class OutreachTests(unittest.TestCase):
    def test_tilda_details_without_brand_name_dropin(self):
        lead={"category":"web","body":"Требуется дизайнер для лендинга на Tilda для маркетингового агентства. Разработка с нуля, 6–9 блоков. Оплата по договорённости."}
        info=analyse_brief(lead)
        self.assertEqual(info["kind"],"web")
        self.assertIn("6–9 блоков",info["facts"])
        self.assertIn("Tilda",info["facts"])
        text,mode,_=create_draft(lead)
        self.assertEqual(mode,"local")
        self.assertIn("6–9 блоков",text)
        self.assertNotIn("Avito",text)
        self.assertNotIn("Haval",text)

    def test_presentation_volume(self):
        lead={"category":"presentations","body":"Срочно нужен дизайнер презентации. 140 слайдов к единому стилю, контент готов, на сегодня."}
        info=analyse_brief(lead)
        self.assertIn("140 слайдов",info["facts"])
        letter,_,_=create_draft(lead)
        self.assertIn("140 слайдов",letter)
        self.assertNotIn("Avito",letter)

    def test_graphic_print(self):
        lead={"category":"branding","body":"Ищу графического дизайнера для упаковки и печатных материалов. Нужен базовый английский и оперативность."}
        info=analyse_brief(lead)
        self.assertEqual(info["kind"],"packaging")
        self.assertIn("печатные материалы",info["facts"])
        for _ in range(5):
            text,_,_=create_draft(lead)
            self.assertIn(PORTFOLIO,text)
            self.assertNotIn("Avito",text)
            self.assertNotIn("директор",text.lower())

    def test_multiple_fresh_generations_are_unique(self):
        lead={"category":"web","body":"Нужен дизайн лендинга на Tilda с нуля. 6–9 блоков, адаптивная версия, проект."}
        previous=[]
        for _ in range(8):
            text,_,_=create_draft(lead,previous=previous)
            self.assertNotIn(text,previous)
            self.assertNotIn("Avito",text)
            self.assertEqual(text.count(PORTFOLIO),1)
            self.assertLess(len(text),950)
            previous.insert(0,text)

    def test_api_output_validation(self):
        info=analyse_brief({"category":"web","body":"Лендинг на Tilda 6–9 блоков"})
        self.assertFalse(valid_draft("Готов! Есть кейс Avito. "+PORTFOLIO,info,[]))
        valid="Здравствуйте! Видел запрос на лендинг на Tilda. Могу разработать страницу из 6–9 блоков и адаптив. Портфолио: https://samsel.site. Уточните сроки?"
        self.assertTrue(valid_draft(valid,info,[]))
        self.assertFalse(valid_draft(valid,info,[valid]))

if __name__=="__main__":
    unittest.main()
