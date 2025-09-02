from setuptools import setup, find_packages

setup(
    name="vpn-telegram-bot",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        'aiogram>=2.25.1',
        'aiohttp>=3.8.4',
        'sqlalchemy>=1.4.46',
        'gino>=1.0.1',
        'requests>=2.28.2',
        'python-dotenv>=1.0.0',
    ],
    entry_points={
        'console_scripts': [
            'vpn-bot=bot.main:main',
        ],
    },
)
