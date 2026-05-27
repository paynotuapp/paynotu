import 'package:flex_color_scheme/flex_color_scheme.dart';
import 'package:flutter/material.dart';

class AppTheme {
  AppTheme._();

  static const _anaYesil = Color(0xFF00C853);

  static ThemeData get light => FlexThemeData.light(
        colors: const FlexSchemeColor(
          primary: _anaYesil,
          primaryContainer: Color(0xFFB9F6CA),
          secondary: Color(0xFF00BFA5),
          secondaryContainer: Color(0xFFA7FFEB),
          tertiary: Color(0xFF1B5E20),
          tertiaryContainer: Color(0xFFC8E6C9),
          appBarColor: _anaYesil,
          error: Color(0xFFB00020),
        ),
        surfaceMode: FlexSurfaceMode.levelSurfacesLowScaffold,
        blendLevel: 7,
        subThemesData: const FlexSubThemesData(
          blendOnLevel: 10,
          blendOnColors: false,
          useM2StyleDividerInM3: true,
          alignedDropdown: true,
          useInputDecoratorThemeInDialogs: true,
        ),
        visualDensity: FlexColorScheme.comfortablePlatformDensity,
        useMaterial3: true,
      );

  static ThemeData get dark => FlexThemeData.dark(
        colors: const FlexSchemeColor(
          primary: _anaYesil,
          primaryContainer: Color(0xFF1B5E20),
          secondary: Color(0xFF00BFA5),
          secondaryContainer: Color(0xFF004D40),
          tertiary: Color(0xFF69F0AE),
          tertiaryContainer: Color(0xFF1B5E20),
          appBarColor: Color(0xFF1A1A1A),
          error: Color(0xFFCF6679),
        ),
        surfaceMode: FlexSurfaceMode.levelSurfacesLowScaffold,
        blendLevel: 13,
        subThemesData: const FlexSubThemesData(
          blendOnLevel: 20,
          useM2StyleDividerInM3: true,
          alignedDropdown: true,
          useInputDecoratorThemeInDialogs: true,
        ),
        visualDensity: FlexColorScheme.comfortablePlatformDensity,
        useMaterial3: true,
      );
}
