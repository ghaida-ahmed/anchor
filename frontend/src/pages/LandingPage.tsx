import { ClosingCtaSection } from '@/features/landing/ClosingCtaSection';
import { FeatureSection } from '@/features/landing/FeatureSection';
import { HeroSection } from '@/features/landing/HeroSection';
import { HowItWorksSection } from '@/features/landing/HowItWorksSection';

export function LandingPage() {
  return (
    <>
      <HeroSection />
      <HowItWorksSection />
      <FeatureSection />
      <ClosingCtaSection />
    </>
  );
}
