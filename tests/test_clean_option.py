"""The 대괄호 표시와 # 줄 빼기 switch: on by default, kept with the project."""

from coverlyric import server
from coverlyric.project import Project


def test_old_projects_keep_cleaning_on(tmp_path):
    assert Project.from_dict(tmp_path, {}).clean_tags is True
    project = Project(tmp_path, clean_tags=False)
    assert Project.from_dict(tmp_path, project.to_dict()).clean_tags is False


def test_the_page_turns_it_off_and_it_is_saved(tmp_path):
    app = server.App(tmp_path)
    assert app.state()["clean_tags"] is True
    app.update({"clean_tags": False})
    app.save()
    assert server.App(tmp_path).project.clean_tags is False
