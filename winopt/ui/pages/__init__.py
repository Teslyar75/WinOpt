"""Страницы приложения."""

from winopt.ui.pages.dashboard import DashboardPage
from winopt.ui.pages.optimize import OptimizePage
from winopt.ui.pages.processes import ProcessesPage
from winopt.ui.pages.startup import StartupPage
from winopt.ui.pages.cleanup import CleanupPage
from winopt.ui.pages.disk import DiskPage
from winopt.ui.pages.programs import ProgramsPage
from winopt.ui.pages.services import ServicesPage
from winopt.ui.pages.network import NetworkPage
from winopt.ui.pages.security import SecurityPage
from winopt.ui.pages.health import HealthPage
from winopt.ui.pages.journal import JournalPage

PAGE_CLASSES = {
    "dashboard": DashboardPage,
    "optimize": OptimizePage,
    "processes": ProcessesPage,
    "startup": StartupPage,
    "cleanup": CleanupPage,
    "disk": DiskPage,
    "programs": ProgramsPage,
    "services": ServicesPage,
    "network": NetworkPage,
    "security": SecurityPage,
    "health": HealthPage,
    "journal": JournalPage,
}
