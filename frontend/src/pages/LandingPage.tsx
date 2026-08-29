import { ClosingCtaSection } from '@/features/landing/ClosingCtaSection';
import { FeatureSection } from '@/features/landing/FeatureSection';
import { HeroSection } from '@/features/landing/HeroSection';
import { HowItWorksSection } from '@/features/landing/HowItWorksSection';
import { RoadmapSection } from '@/features/landing/RoadmapSection';

export function LandingPage() {
  return (
    <>
      <HeroSection />
      <HowItWorksSection />
      <FeatureSection />
      <RoadmapSection />
      <ClosingCtaSection />
    </>
  );
}
